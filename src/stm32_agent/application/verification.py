from __future__ import annotations

from pathlib import Path
from typing import Any

from ..infrastructure import project as project_ops
from ..infrastructure import state as state_store


def prepare_workspace(
    project: project_ops.ProjectConfig,
    *,
    backend: str | None = None,
) -> Path:
    workspace = project_ops.require_path(project.workspace, "workspace is required")
    state_store.update_project_profile(project, workspace, backend=backend)
    return workspace


def record_verification(
    workspace: Path,
    *,
    action: str,
    ok: bool,
    summary: str,
    verification_status: str,
    evidence: dict[str, Any] | None = None,
    state: dict[str, Any] | None = None,
) -> None:
    state_store.append_verification(
        workspace,
        action=action,
        ok=ok,
        summary=summary,
        verification_status=verification_status,
        evidence=evidence,
        state=state,
    )


def record_session_transition(
    workspace: Path,
    *,
    session: dict[str, Any],
    action: str,
    status: str,
    summary: str,
    verification_status: str,
    source: dict[str, Any] | None = None,
    registers: dict[str, str] | None = None,
    observation: dict[str, Any] | None = None,
    evidence: dict[str, Any] | None = None,
    state: dict[str, Any] | None = None,
) -> None:
    state_store.update_session_state(
        workspace,
        session=session,
        status=status,
        action=action,
        source=source,
        registers=registers,
        summary=summary,
    )
    if observation is not None:
        state_store.append_observation(workspace, observation)
    record_verification(
        workspace,
        action=action,
        ok=True,
        summary=summary,
        verification_status=verification_status,
        evidence=evidence,
        state=state,
    )
