from __future__ import annotations

import json
import time
from dataclasses import replace
from pathlib import Path
from typing import Any

import typer

from ...contracts import SessionState, VerificationEntry
from ..project import ProjectConfig
from .paths import (
    compact_path,
    ensure_state_dirs,
    observation_file,
    project_profile_file,
    read_json,
    session_file,
    session_state_file,
    verification_report_file,
    write_json,
)


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
    entry = VerificationEntry(
        timestamp=int(time.time()),
        action=action,
        ok=ok,
        summary=summary,
        verification_status=verification_status,
        evidence=evidence or {},
        state=state or {},
    )
    entries.append(entry.to_dict())
    payload["entries"] = entries[-limit:]
    payload["latest"] = payload["entries"][-1]
    write_json(path, payload)


def build_session_state_payload(
    workspace: Path,
    current: dict[str, Any],
    *,
    session_id: str | None = None,
    status: str | None = None,
    action: str | None = None,
    session: dict[str, Any] | None = None,
    source: dict[str, Any] | None = None,
    registers: dict[str, str] | None = None,
    summary: str | None = None,
    lock_state: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if lock_state is None:
        from .lock import current_session_lock_state

        lock_state = current_session_lock_state(workspace)

    current_state = SessionState.from_dict(workspace, current)
    payload = replace(
        current_state,
        session_id=session_id or (session or {}).get("session_id") or current_state.session_id,
        backend=(session or {}).get("backend", current_state.backend),
        status=status or current_state.status,
        last_action=action or current_state.last_action,
        updated_at=int(time.time()),
        source=source if source is not None else current_state.source,
        registers_compact=registers if registers is not None else current_state.registers_compact,
        summary=summary if summary is not None else current_state.summary,
        lock=lock_state,
        gdb_port=(session or {}).get("gdb_port", current_state.gdb_port),
        server_kind=(session or {}).get("server_kind", current_state.server_kind),
        server_pid=(session or {}).get("server_pid", current_state.server_pid),
    )
    return payload.to_dict()


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
    payload = build_session_state_payload(
        workspace,
        current,
        status=status,
        action=action,
        session=session,
        source=source,
        registers=registers,
        summary=summary,
    )
    write_json(session_state_file(workspace), payload)


def latest_verification_entry(workspace: Path) -> dict[str, Any]:
    payload = read_json(verification_report_file(workspace))
    latest = VerificationEntry.from_dict(payload.get("latest") if isinstance(payload, dict) else {})
    return latest.to_dict() if latest is not None else {}


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
