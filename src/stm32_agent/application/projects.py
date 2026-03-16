from __future__ import annotations

from pathlib import Path

from ..infrastructure import project as project_ops


def load_project(config: Path | None) -> project_ops.ProjectConfig:
    return project_ops.load_config(config)


def resolve_project(
    config: Path | None,
    **overrides: object,
) -> project_ops.ProjectConfig:
    return project_ops.merge_config(load_project(config), **overrides)
