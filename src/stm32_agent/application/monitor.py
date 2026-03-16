from __future__ import annotations

import time
from pathlib import Path
from typing import Callable

import serial
import typer

from ..contracts import MonitorEvent, MonitorResult
from ..infrastructure import project as project_ops
from ..infrastructure import state as state_store
from . import verification as verify_tools


def run_monitor(
    project: project_ops.ProjectConfig,
    *,
    serial_port: str | None = None,
    baudrate: int | None = None,
    duration: float = 0.0,
    log_file: Path | None = None,
    raw: bool = False,
    on_event: Callable[[MonitorEvent], None] | None = None,
) -> MonitorResult:
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

    start_time = time.monotonic()
    line_count = 0
    handle = None
    if on_event is not None:
        on_event(
            MonitorEvent(
                kind="status",
                text=f"monitoring {port} @ {resolved_baudrate}",
                port=port,
                baudrate=resolved_baudrate,
            )
        )
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
                timestamp = None if raw else time.strftime("%H:%M:%S")
                rendered = text if raw else f"[{timestamp}] {text}"
                line_count += 1
                if on_event is not None:
                    on_event(
                        MonitorEvent(
                            kind="line",
                            text=rendered,
                            port=port,
                            baudrate=resolved_baudrate,
                            timestamp=timestamp,
                        )
                    )
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
        return MonitorResult(
            summary=f"Monitor session completed on {port}.",
            port=port,
            baudrate=resolved_baudrate,
            duration=duration,
            raw=raw,
            interrupted=False,
            line_count=line_count,
            log_file=state_store.compact_path(str(resolved_log_file)) if resolved_log_file else None,
        )
    except KeyboardInterrupt:
        if on_event is not None:
            on_event(
                MonitorEvent(
                    kind="status",
                    text="monitor interrupted",
                    port=port,
                    baudrate=resolved_baudrate,
                )
            )
        return MonitorResult(
            summary=f"Monitor interrupted on {port}.",
            port=port,
            baudrate=resolved_baudrate,
            duration=duration,
            raw=raw,
            interrupted=True,
            line_count=line_count,
            log_file=state_store.compact_path(str(resolved_log_file)) if resolved_log_file else None,
        )
    except serial.SerialException as exc:
        raise typer.BadParameter(str(exc)) from exc
    finally:
        if handle is not None:
            handle.close()
