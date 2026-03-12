from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

import typer

from ..infrastructure import debug_support as debug_ops
from ..infrastructure import project as project_ops
from ..infrastructure import state as state_store
from . import verification_service as verify_tools


@contextmanager
def locked_session(
    project: project_ops.ProjectConfig,
    *,
    action: str,
) -> Iterator[tuple[Path, dict[str, Any]]]:
    resolved_workspace = project_ops.require_path(project.workspace, "workspace is required")
    with state_store.session_command_lock(resolved_workspace, action=action):
        yield debug_ops.resolve_session(project)


def step_debug_session(project: project_ops.ProjectConfig, *, instruction: bool = True) -> None:
    step_command = "stepi" if instruction else "step"
    with locked_session(project, action="debug_step") as (resolved_workspace, session):
        completed = debug_ops.session_gdb_command(project, ["monitor halt", step_command, "bt"])
        source = debug_ops.extract_source_location(completed.stdout)
        _record_halted_capture(
            resolved_workspace,
            session=session,
            action="debug_step",
            source=source,
            summary=f"Single step completed at {source.get('symbol', 'unknown location')}.",
            observation={
                "kind": "debug_step",
                "mode": step_command,
                "source": source,
                "raw_excerpt": debug_ops.trim_lines(completed.stdout),
            },
            verification_evidence={
                "session_path": state_store.compact_path(str(state_store.session_file(resolved_workspace)))
            },
            verification_state={"source": source},
        )


def continue_debug_session(project: project_ops.ProjectConfig, *, address: str | None = None) -> None:
    with locked_session(project, action="debug_continue") as (resolved_workspace, session):
        commands: list[str] = []
        if address is not None:
            commands.append(f"set $pc = {address}")
        commands.extend(["continue&", "disconnect"])
        debug_ops.session_gdb_command(project, commands)
        summary = "Target resumed asynchronously."
        state_store.update_session_state(
            resolved_workspace,
            session=session,
            status="running",
            action="debug_continue",
            summary=summary,
        )
        state_store.append_observation(
            resolved_workspace,
            {
                "kind": "debug_continue",
                "resume_address": address,
                "summary": summary,
            },
        )
        state_store.append_verification(
            resolved_workspace,
            action="debug_continue",
            ok=True,
            summary=summary,
            verification_status="hardware_verified",
            state={"resume_address": address},
        )
        typer.echo("target resumed")


def dump_registers(project: project_ops.ProjectConfig) -> None:
    with locked_session(project, action="debug_registers") as (resolved_workspace, session):
        completed = debug_ops.session_gdb_command(project, ["monitor halt", "info registers"])
        source = debug_ops.extract_source_location(completed.stdout)
        registers = debug_ops.extract_registers(completed.stdout)
        compact_registers = {key: value for key, value in registers.items() if key in {"sp", "lr", "pc", "control"}}
        _record_halted_capture(
            resolved_workspace,
            session=session,
            action="debug_registers",
            source=source,
            registers=compact_registers,
            summary=f"Registers captured at {source.get('symbol', 'unknown location')}.",
            observation={
                "kind": "registers",
                "source": source,
                "registers_compact": compact_registers,
                "raw_excerpt": debug_ops.trim_lines(completed.stdout),
            },
            verification_state={"source": source},
        )


def dump_backtrace(project: project_ops.ProjectConfig) -> None:
    with locked_session(project, action="debug_backtrace") as (resolved_workspace, session):
        completed = debug_ops.session_gdb_command(project, ["monitor halt", "bt"])
        source = debug_ops.extract_source_location(completed.stdout)
        _record_halted_capture(
            resolved_workspace,
            session=session,
            action="debug_backtrace",
            source=source,
            summary=f"Backtrace captured at {source.get('symbol', 'unknown location')}.",
            observation={
                "kind": "backtrace",
                "source": source,
                "raw_excerpt": debug_ops.trim_lines(completed.stdout),
            },
            verification_state={"source": source},
        )


def _record_halted_capture(
    resolved_workspace: Path,
    *,
    session: dict[str, Any],
    action: str,
    source: dict[str, Any],
    summary: str,
    observation: dict[str, Any],
    registers: dict[str, str] | None = None,
    verification_evidence: dict[str, Any] | None = None,
    verification_state: dict[str, Any] | None = None,
) -> None:
    verify_tools.record_session_transition(
        resolved_workspace,
        session=session,
        action=action,
        status="halted",
        summary=summary,
        verification_status="hardware_verified",
        source=source,
        registers=registers,
        observation=observation,
        evidence=verification_evidence,
        state=verification_state,
    )
