from __future__ import annotations

from pathlib import Path
from typing import Any

from ..infrastructure import state as state_store


def _state_files(workspace: Path) -> dict[str, str]:
    return {
        "project_profile": state_store.compact_path(str(state_store.project_profile_file(workspace))),
        "session_state": state_store.compact_path(str(state_store.session_state_file(workspace))),
        "observation": state_store.compact_path(str(state_store.observation_file(workspace))),
        "verification_report": state_store.compact_path(str(state_store.verification_report_file(workspace))),
    }


def _build_runtime_summary(
    workspace: Path,
    session_state: dict[str, Any],
    latest_verification: dict[str, Any],
) -> dict[str, Any]:
    lock = session_state.get("lock") if isinstance(session_state.get("lock"), dict) else {}
    status = session_state.get("status") or "unknown"
    return {
        "session_active": state_store.session_file(workspace).exists(),
        "session_status": status,
        "session_busy": bool(lock.get("busy")),
        "busy_action": lock.get("action"),
        "backend": session_state.get("backend"),
        "last_action": session_state.get("last_action"),
        "last_verification_status": latest_verification.get("verification_status"),
    }


def _recommended_actions(
    project_profile: dict[str, Any],
    session_state: dict[str, Any],
    latest_verification: dict[str, Any],
) -> list[str]:
    lock = session_state.get("lock") if isinstance(session_state.get("lock"), dict) else {}
    status = session_state.get("status")
    actions: list[str] = []

    if lock.get("busy"):
        actions.append("wait_for_active_tool_completion")
        return actions

    if not project_profile.get("svd"):
        actions.append("svd fetch")
    if not project_profile.get("elf"):
        actions.append("build")

    if status in {None, "", "unknown", "stopped"}:
        actions.append("flash")
        actions.append("debug start")
    elif status == "running":
        actions.append("debug snapshot")
        actions.append("debug registers")
    elif status == "halted":
        actions.append("debug backtrace")
        actions.append("debug continue")

    if latest_verification.get("ok") is False:
        actions.insert(0, "inspect verification_report and retry the failed tool")

    # Preserve order while removing duplicates.
    return list(dict.fromkeys(actions))


def build_agent_context(
    workspace: Path,
    *,
    observation_limit: int = 4,
) -> dict[str, Any]:
    resolved_workspace = workspace.resolve()
    project_profile = state_store.read_json(state_store.project_profile_file(resolved_workspace))
    session_state = state_store.read_session_state(resolved_workspace)
    recent_observations = state_store.recent_observations(resolved_workspace, limit=observation_limit)
    latest_verification = state_store.latest_verification_entry(resolved_workspace)

    return {
        "workspace": state_store.compact_path(str(resolved_workspace)),
        "state_files": _state_files(resolved_workspace),
        "capabilities": {
            "build": True,
            "flash": True,
            "debug": True,
            "monitor": True,
            "svd": True,
            "verification": True,
        },
        "runtime": _build_runtime_summary(
            resolved_workspace,
            session_state,
            latest_verification,
        ),
        "recommended_actions": _recommended_actions(
            project_profile,
            session_state,
            latest_verification,
        ),
        "project_profile": project_profile,
        "session_state": session_state,
        "recent_observations": recent_observations,
        "latest_verification": latest_verification,
    }
