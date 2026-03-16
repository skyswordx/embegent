from __future__ import annotations

import json
from typing import Any

import typer

from ..contracts import (
    BuildResult,
    CommandRunResult,
    DebugCommandResult,
    DoctorResult,
    ExecutionSnapshot,
    FlashResult,
    MonitorEvent,
    MonitorResult,
    PeripheralReadResult,
    SvdFetchResult,
)


def render_doctor(result: DoctorResult) -> None:
    typer.echo(f"{'backend':18} {result.backend}")
    for check in result.checks:
        typer.echo(f"{check.name:18} {check.result}")


def render_svd_fetch(result: SvdFetchResult) -> None:
    status = "reused" if result.reused else "fetched"
    typer.echo(f"SVD {status}: {result.candidate_name} -> {result.local_path}")


def render_debug_command(result: DebugCommandResult) -> None:
    if result.command:
        typer.echo("$ " + " ".join(result.command))
    typer.echo(result.summary)


def _render_command_result(result: CommandRunResult) -> None:
    typer.echo("$ " + " ".join(result.command))
    if result.stdout.strip():
        typer.echo(result.stdout.rstrip())
    if result.stderr.strip():
        typer.echo(result.stderr.rstrip(), err=True)


def render_build_result(result: BuildResult) -> None:
    for step in result.steps:
        _render_command_result(step)
    typer.echo(result.summary)


def render_flash_result(result: FlashResult) -> None:
    _render_command_result(result.command_result)
    typer.echo(result.summary)


def render_debug_startup_error(error: Any) -> None:
    if getattr(error, "log_text", "").strip():
        typer.echo(error.log_text.rstrip(), err=True)
    if getattr(error, "log_path", None):
        typer.echo(f"startup log: {error.log_path}", err=True)


def render_snapshot(snapshot: ExecutionSnapshot) -> None:
    typer.echo(json.dumps(snapshot.to_dict(), indent=2, ensure_ascii=False))


def render_peripheral_read(result: PeripheralReadResult) -> None:
    typer.echo(result.summary)
    for item in result.decoded:
        typer.echo(f"{item.register} @ {item.address} = {item.value_hex}")
        for field in item.fields[:8]:
            high_bit = field.bit_offset + field.bit_width - 1
            typer.echo(f"  {field.name}[{field.bit_offset}:{high_bit}] = {field.value_hex}")
        if len(item.fields) > 8:
            typer.echo(f"  ... {len(item.fields) - 8} more fields")


def render_monitor_event(event: MonitorEvent) -> None:
    typer.echo(event.text)


def render_monitor_result(result: MonitorResult) -> None:
    typer.echo(result.summary)
