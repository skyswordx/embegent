from __future__ import annotations

import os
import shutil
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

import typer

from .state_paths import (
    ensure_state_dirs,
    read_json,
    session_lock_dir,
    session_lock_file,
    session_state_file,
    write_json,
)
from .state_runtime import build_session_state_payload


def read_session_lock(workspace: Path) -> dict[str, Any]:
    return read_json(session_lock_file(workspace))


def clear_session_lock(workspace: Path) -> None:
    lock_dir = session_lock_dir(workspace)
    if lock_dir.exists():
        shutil.rmtree(lock_dir, ignore_errors=True)


def _lock_age_seconds(workspace: Path, now: float) -> float:
    lock_meta = read_session_lock(workspace)
    acquired_at = lock_meta.get("acquired_at")
    if isinstance(acquired_at, (int, float)):
        return max(0.0, now - float(acquired_at))

    lock_dir = session_lock_dir(workspace)
    try:
        return max(0.0, now - lock_dir.stat().st_mtime)
    except FileNotFoundError:
        return 0.0


def current_session_lock_state(workspace: Path) -> dict[str, Any]:
    lock_dir = session_lock_dir(workspace)
    lock_meta = read_session_lock(workspace)
    if not lock_dir.exists():
        return {
            "busy": False,
            "status": "idle",
        }

    now = time.time()
    state: dict[str, Any] = {
        "busy": True,
        "status": "busy",
        "action": lock_meta.get("action"),
        "pid": lock_meta.get("pid"),
        "acquired_at": lock_meta.get("acquired_at"),
        "age_seconds": round(_lock_age_seconds(workspace, now), 3),
    }
    return {key: value for key, value in state.items() if value is not None}


def write_session_lock_state(workspace: Path, lock_state: dict[str, Any]) -> None:
    ensure_state_dirs(workspace)
    path = session_state_file(workspace)
    current = read_json(path)
    payload = build_session_state_payload(
        workspace,
        current,
        lock_state=lock_state,
    )
    write_json(path, payload)


def read_session_state(workspace: Path) -> dict[str, Any]:
    payload = read_json(session_state_file(workspace))
    if not payload:
        return {}
    payload["lock"] = current_session_lock_state(workspace)
    return payload


@contextmanager
def session_command_lock(
    workspace: Path,
    *,
    action: str,
    timeout: float = 20.0,
    poll_interval: float = 0.2,
    stale_after: float = 1800.0,
) -> Iterator[dict[str, Any]]:
    ensure_state_dirs(workspace)
    lock_dir = session_lock_dir(workspace)
    lock_file = session_lock_file(workspace)
    start_wait = time.monotonic()
    metadata = {
        "action": action,
        "pid": os.getpid(),
        "acquired_at": time.time(),
    }

    while True:
        try:
            lock_dir.mkdir()
            write_json(lock_file, metadata)
            write_session_lock_state(workspace, current_session_lock_state(workspace))
            break
        except FileExistsError:
            now = time.time()
            age = _lock_age_seconds(workspace, now)
            current = read_session_lock(workspace)
            if age >= stale_after:
                clear_session_lock(workspace)
                continue

            if (time.monotonic() - start_wait) >= timeout:
                owner_action = current.get("action", "unknown")
                owner_pid = current.get("pid", "unknown")
                raise typer.BadParameter(
                    f"debug session is busy with {owner_action} (pid={owner_pid}); retry after it completes"
                )

            time.sleep(poll_interval)

    try:
        yield metadata
    finally:
        current = read_session_lock(workspace)
        if current.get("pid") == metadata["pid"] and current.get("action") == metadata["action"]:
            clear_session_lock(workspace)
        write_session_lock_state(workspace, current_session_lock_state(workspace))
