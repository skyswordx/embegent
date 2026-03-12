from __future__ import annotations

import os
import json
import shutil
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

import typer

from .project import ProjectConfig


def state_dir(workspace: Path) -> Path:
    return workspace / ".stm32-agent"


def logs_dir(workspace: Path) -> Path:
    return state_dir(workspace) / "logs"


def session_file(workspace: Path) -> Path:
    return state_dir(workspace) / "session.json"


def session_lock_dir(workspace: Path) -> Path:
    return state_dir(workspace) / "session.lock"


def session_lock_file(workspace: Path) -> Path:
    return session_lock_dir(workspace) / "lock.json"


def project_profile_file(workspace: Path) -> Path:
    return state_dir(workspace) / "project_profile.json"


def session_state_file(workspace: Path) -> Path:
    return state_dir(workspace) / "session_state.json"


def observation_file(workspace: Path) -> Path:
    return state_dir(workspace) / "observation.json"


def verification_report_file(workspace: Path) -> Path:
    return state_dir(workspace) / "verification_report.json"


def svd_dir(workspace: Path) -> Path:
    return state_dir(workspace) / "svd"


def ensure_state_dirs(workspace: Path) -> None:
    logs_dir(workspace).mkdir(parents=True, exist_ok=True)
    svd_dir(workspace).mkdir(parents=True, exist_ok=True)


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")


def read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def write_session(workspace: Path, payload: dict[str, Any]) -> None:
    ensure_state_dirs(workspace)
    write_json(session_file(workspace), payload)


def read_session(workspace: Path) -> dict[str, Any]:
    path = session_file(workspace)
    if not path.exists():
        raise typer.BadParameter(f"session file not found: {path}")
    return json.loads(path.read_text(encoding="utf-8"))


def remove_session(workspace: Path) -> None:
    path = session_file(workspace)
    if path.exists():
        path.unlink()


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
    payload = {
        "session_id": current.get("session_id") or f"{workspace.name}-{int(time.time())}",
        "workspace": compact_path(str(workspace)),
        "backend": current.get("backend"),
        "status": current.get("status", "unknown"),
        "last_action": current.get("last_action"),
        "updated_at": int(time.time()),
        "source": current.get("source"),
        "registers_compact": current.get("registers_compact"),
        "summary": current.get("summary"),
        "lock": lock_state,
    }
    for key in ("gdb_port", "server_kind", "server_pid"):
        if key in current:
            payload[key] = current[key]
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


def compact_path(path: str | None) -> str | None:
    if path is None:
        return None
    return path.replace("\\", "/")


def update_project_profile(project: ProjectConfig, workspace: Path, *, backend: str | None = None) -> None:
    ensure_state_dirs(workspace)
    current = read_json(project_profile_file(workspace))
    payload = {
        "project_name": project.project_name or current.get("project_name") or workspace.name,
        "workspace": compact_path(str(workspace)),
        "elf": compact_path(str(project.elf)) if project.elf else current.get("elf"),
        "build_dir": compact_path(str(project.build_dir)) if project.build_dir else current.get("build_dir"),
        "chip": current.get("chip"),
        "probe": project.probe or current.get("probe"),
        "backend": backend or project.backend or current.get("backend") or "openocd",
        "rtos": current.get("rtos", "unknown"),
        "serial_port": project.serial_port or current.get("serial_port"),
        "baudrate": project.baudrate or current.get("baudrate"),
        "configure_preset": project.configure_preset or current.get("configure_preset"),
        "build_preset": project.build_preset or current.get("build_preset"),
        "svd": current.get("svd"),
        "generated_at": int(time.time()),
    }
    write_json(project_profile_file(workspace), payload)


def load_observation(workspace: Path) -> dict[str, Any]:
    payload = read_json(observation_file(workspace))
    if not payload:
        payload = {"history": []}
    payload.setdefault("history", [])
    return payload


def append_observation(workspace: Path, event: dict[str, Any], *, limit: int = 12) -> None:
    ensure_state_dirs(workspace)
    payload = load_observation(workspace)
    history = payload.setdefault("history", [])
    history.append(event)
    payload["history"] = history[-limit:]
    payload["latest"] = event
    payload["updated_at"] = int(time.time())
    write_json(observation_file(workspace), payload)


def append_verification(
    workspace: Path,
    *,
    action: str,
    ok: bool,
    summary: str,
    verification_status: str,
    evidence: dict[str, Any] | None = None,
    state: dict[str, Any] | None = None,
    limit: int = 20,
) -> None:
    ensure_state_dirs(workspace)
    path = verification_report_file(workspace)
    payload = read_json(path) or {"entries": []}
    entries = payload.setdefault("entries", [])
    entries.append(
        {
            "timestamp": int(time.time()),
            "action": action,
            "ok": ok,
            "summary": summary,
            "verification_status": verification_status,
            "evidence": evidence or {},
            "state": state or {},
        }
    )
    payload["entries"] = entries[-limit:]
    payload["latest"] = payload["entries"][-1]
    write_json(path, payload)


def update_session_state(
    workspace: Path,
    *,
    session: dict[str, Any] | None = None,
    status: str,
    action: str,
    source: dict[str, Any] | None = None,
    registers: dict[str, str] | None = None,
    summary: str | None = None,
) -> None:
    ensure_state_dirs(workspace)
    current = read_json(session_state_file(workspace))
    payload = {
        "session_id": current.get("session_id") or f"{workspace.name}-{int(time.time())}",
        "workspace": compact_path(str(workspace)),
        "backend": (session or {}).get("backend", current.get("backend")),
        "status": status,
        "last_action": action,
        "updated_at": int(time.time()),
        "source": source or current.get("source"),
        "registers_compact": registers or current.get("registers_compact"),
        "summary": summary or current.get("summary"),
        "lock": current_session_lock_state(workspace),
    }
    if session:
        payload["gdb_port"] = session.get("gdb_port")
        payload["server_kind"] = session.get("server_kind")
        payload["server_pid"] = session.get("server_pid")
    write_json(session_state_file(workspace), payload)


def latest_verification_entry(workspace: Path) -> dict[str, Any]:
    payload = read_json(verification_report_file(workspace))
    latest = payload.get("latest")
    return latest if isinstance(latest, dict) else {}


def compact_observation_event(event: dict[str, Any]) -> dict[str, Any]:
    compact: dict[str, Any] = {
        "kind": event.get("kind"),
    }
    for key in (
        "source",
        "summary",
        "peripheral",
        "svd_path",
        "mode",
        "resume_address",
        "port",
        "baudrate",
        "log_file",
    ):
        value = event.get(key)
        if value is not None:
            compact[key] = value

    if event.get("registers_compact"):
        compact["registers_compact"] = event["registers_compact"]
    if event.get("line"):
        compact["line"] = event["line"]
    if event.get("raw_excerpt"):
        compact["raw_excerpt"] = event["raw_excerpt"][:6]
    if event.get("decoded"):
        compact["decoded"] = [
            {
                "name": item.get("name"),
                "address": item.get("address"),
                "value_hex": item.get("value_hex"),
                "fields": [
                    {
                        "name": field.get("name"),
                        "value_hex": field.get("value_hex"),
                    }
                    for field in item.get("fields", [])[:6]
                ],
            }
            for item in event["decoded"][:3]
        ]
    return compact


def recent_observations(workspace: Path, limit: int = 4) -> list[dict[str, Any]]:
    payload = load_observation(workspace)
    history = payload.get("history", [])
    if not isinstance(history, list):
        return []
    return [compact_observation_event(item) for item in history[-limit:]]
