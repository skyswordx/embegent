from __future__ import annotations

import subprocess
import time
from pathlib import Path

import typer

from .. import debug_support as debug_ops
from .. import project as project_ops
from .. import state as state_store


def start_debug_session(
    project: project_ops.ProjectConfig,
    *,
    backend: str | None = None,
    openocd_path: str | None = None,
    stlink_gdb_server_path: str | None = None,
    cubeprogrammer_path: str | None = None,
    gdb_port: int = 3333,
    dry_run: bool = False,
) -> None:
    resolved_workspace = project_ops.require_path(project.workspace, "workspace is required")
    resolved_elf = project_ops.require_path(project.elf, "elf is required")

    resolved_backend = project_ops.resolve_backend(project, backend)
    interface_path = None
    target_path = None
    gdb_port_value = project.gdb_port or gdb_port

    if resolved_backend == "openocd":
        resolved_interface = project_ops.resolve_interface_cfg(project.probe, project.interface_cfg)
        if not resolved_interface:
            raise typer.BadParameter("interface_cfg is required unless probe maps to a known interface")
        if not project.target_cfg:
            raise typer.BadParameter("target_cfg is required")
        openocd = openocd_path or project_ops.resolve_executable("openocd", "OPENOCD")
        if not openocd:
            raise typer.BadParameter("openocd was not found. Add it to PATH or set OPENOCD.")
        interface_path = project_ops.resolve_cfg_path(resolved_workspace, resolved_interface)
        target_path = project_ops.resolve_cfg_path(resolved_workspace, project.target_cfg)
        command = [
            openocd,
            "-f",
            interface_path,
            "-f",
            target_path,
            "-c",
            f"gdb_port {gdb_port_value}",
        ]
        command.extend(project.openocd_args)
        session_kind = "openocd"
    elif resolved_backend == "stlink":
        stlink_gdbserver = stlink_gdb_server_path or project_ops.resolve_executable("stlink_gdbserver", "STLINK_GDB_SERVER")
        if not stlink_gdbserver:
            raise typer.BadParameter(
                "ST-LINK_gdbserver was not found. Add it to PATH or set STLINK_GDB_SERVER."
            )
        cubeprogrammer_dir = _resolve_cubeprogrammer_dir(cubeprogrammer_path)
        command = [stlink_gdbserver, "-e", "-d", "-p", str(gdb_port_value)]
        if cubeprogrammer_dir:
            command.extend(["-cp", cubeprogrammer_dir])
        if project.serial_number:
            command.extend(["-i", project.serial_number])
        if project.frequency_khz:
            command.extend(["--frequency", str(project.frequency_khz)])
        command.extend(project.stlink_gdb_server_args)
        session_kind = "stlink_gdbserver"
    else:
        raise typer.BadParameter(f"Unsupported backend: {resolved_backend}")

    typer.echo("$ " + " ".join(command))
    if dry_run:
        return

    with state_store.session_command_lock(resolved_workspace, action="debug_start"):
        session_path = state_store.session_file(resolved_workspace)
        if session_path.exists():
            raise typer.BadParameter(f"debug session already exists: {session_path}")

        payload = _spawn_debug_server(
            command=command,
            resolved_workspace=resolved_workspace,
            resolved_elf=resolved_elf,
            resolved_backend=resolved_backend,
            session_kind=session_kind,
            project=project,
            interface_path=interface_path,
            target_path=target_path,
            gdb_port_value=gdb_port_value,
        )
        state_store.write_session(resolved_workspace, payload)
        state_store.update_project_profile(project, resolved_workspace, backend=resolved_backend)
        state_store.update_session_state(
            resolved_workspace,
            session=payload,
            status="halted_or_waiting",
            action="debug_start",
            summary=f"Debug session started with {session_kind}.",
        )
        state_store.append_verification(
            resolved_workspace,
            action="debug_start",
            ok=True,
            summary="Debug session started.",
            verification_status="hardware_verified",
            evidence={
                "session_path": state_store.compact_path(str(state_store.session_file(resolved_workspace))),
                "server_log": state_store.compact_path(str(payload["server_log"])),
            },
            state={"backend": resolved_backend, "server_kind": session_kind},
        )
        typer.echo(f"session started: {session_path}")


def stop_debug_session(project: project_ops.ProjectConfig) -> None:
    resolved_workspace = project_ops.require_path(project.workspace, "workspace is required")
    with state_store.session_command_lock(resolved_workspace, action="debug_stop"):
        session = state_store.read_session(resolved_workspace)
        pid = int(session["server_pid"])
        debug_ops.terminate_pid(pid)
        state_store.remove_session(resolved_workspace)
        state_store.update_session_state(
            resolved_workspace,
            session=session,
            status="stopped",
            action="debug_stop",
            summary=f"Debug session stopped for pid={pid}.",
        )
        state_store.append_verification(
            resolved_workspace,
            action="debug_stop",
            ok=True,
            summary="Debug session stopped.",
            verification_status="cli_verified",
            state={"server_pid": pid},
        )
        typer.echo(f"session stopped: pid={pid}")


def _resolve_cubeprogrammer_dir(cubeprogrammer_path: str | None) -> str | None:
    if cubeprogrammer_path:
        return str(Path(cubeprogrammer_path).resolve().parent)
    cubeprogrammer = project_ops.resolve_executable("stm32_programmer_cli", "STM32_PROGRAMMER_CLI")
    if cubeprogrammer:
        return str(Path(cubeprogrammer).resolve().parent)
    return None


def _spawn_debug_server(
    *,
    command: list[str],
    resolved_workspace: Path,
    resolved_elf: Path,
    resolved_backend: str,
    session_kind: str,
    project: project_ops.ProjectConfig,
    interface_path: str | None,
    target_path: str | None,
    gdb_port_value: int,
) -> dict[str, object]:
    state_store.ensure_state_dirs(resolved_workspace)
    timestamp = int(time.time())
    server_log = state_store.logs_dir(resolved_workspace) / f"openocd-{timestamp}.log"
    with server_log.open("w", encoding="utf-8") as handle:
        process = subprocess.Popen(
            command,
            cwd=str(resolved_workspace),
            stdout=handle,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
        )

    time.sleep(1.0)
    if process.poll() is not None:
        log_text = server_log.read_text(encoding="utf-8", errors="replace") if server_log.exists() else ""
        typer.echo(log_text.rstrip(), err=True)
        raise typer.Exit(process.returncode or 1)

    return {
        "workspace": str(resolved_workspace),
        "elf": str(resolved_elf),
        "backend": resolved_backend,
        "probe": project.probe,
        "interface_cfg": interface_path,
        "target_cfg": target_path,
        "gdb_port": gdb_port_value,
        "server_kind": session_kind,
        "server_pid": process.pid,
        "server_log": str(server_log),
        "started_at": timestamp,
    }
