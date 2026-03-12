from __future__ import annotations

from pathlib import Path
from typing import Any

from .. import state as state_store


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
