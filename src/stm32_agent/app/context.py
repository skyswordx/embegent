from __future__ import annotations

from pathlib import Path
from typing import Any

from .. import state as state_store


def build_agent_context(
    workspace: Path,
    *,
    observation_limit: int = 4,
) -> dict[str, Any]:
    resolved_workspace = workspace.resolve()
    return {
        "project_profile": state_store.read_json(state_store.project_profile_file(resolved_workspace)),
        "session_state": state_store.read_session_state(resolved_workspace),
        "recent_observations": state_store.recent_observations(resolved_workspace, limit=observation_limit),
        "latest_verification": state_store.latest_verification_entry(resolved_workspace),
    }
