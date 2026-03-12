from __future__ import annotations

import json
from pathlib import Path
from typing import Any


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


def compact_path(path: str | None) -> str | None:
    if path is None:
        return None
    return path.replace("\\", "/")
