from __future__ import annotations

import time
from pathlib import Path

import serial
import typer

from ..infrastructure import project as project_ops
from ..infrastructure import state as state_store
from . import verification_service as verify_tools


def run_monitor(
    project: project_ops.ProjectConfig,
    *,
    serial_port: str | None = None,
    baudrate: int | None = None,
    duration: float = 0.0,
    log_file: Path | None = None,
    raw: bool = False,
) -> None:
    resolved_workspace = verify_tools.prepare_workspace(project)
    port = serial_port or project.serial_port
    if not port:
        raise typer.BadParameter("serial_port is required")

    resolved_baudrate = baudrate or project.baudrate
    if not resolved_baudrate:
        raise typer.BadParameter("baudrate is required")

    resolved_log_file = log_file
    if resolved_log_file is not None and not resolved_log_file.is_absolute():
        resolved_log_file = resolved_workspace / resolved_log_file
    if resolved_log_file is not None:
        resolved_log_file.parent.mkdir(parents=True, exist_ok=True)

    typer.echo(f"monitoring {port} @ {resolved_baudrate}")
    start_time = time.monotonic()
    handle = None
    try:
        if resolved_log_file is not None:
            handle = resolved_log_file.open("a", encoding="utf-8")

        with serial.Serial(port=port, baudrate=resolved_baudrate, timeout=0.2) as device:
            while True:
                if duration > 0 and (time.monotonic() - start_time) >= duration:
                    break

                chunk = device.readline()
                if not chunk:
                    continue

                text = chunk.decode("utf-8", errors="replace").rstrip("\r\n")
                rendered = text if raw else f"[{time.strftime('%H:%M:%S')}] {text}"
                typer.echo(rendered)
                if handle is not None:
                    handle.write(rendered + "\n")
                    handle.flush()
                state_store.append_observation(
                    resolved_workspace,
                    {
                        "kind": "monitor",
                        "port": port,
                        "baudrate": resolved_baudrate,
                        "line": rendered,
                        "log_file": state_store.compact_path(str(resolved_log_file)) if resolved_log_file else None,
                    },
                )
        verify_tools.record_verification(
            resolved_workspace,
            action="monitor",
            ok=True,
            summary=f"Monitor session completed on {port}.",
            verification_status="hardware_verified",
            evidence={
                "log_file": state_store.compact_path(str(resolved_log_file)) if resolved_log_file else None,
            },
            state={"port": port, "baudrate": resolved_baudrate},
        )
    except KeyboardInterrupt:
        typer.echo("monitor interrupted")
    except serial.SerialException as exc:
        raise typer.BadParameter(str(exc)) from exc
    finally:
        if handle is not None:
            handle.close()
