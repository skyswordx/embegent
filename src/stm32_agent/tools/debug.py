from __future__ import annotations

import json
import subprocess
import time
from pathlib import Path

import typer

from .. import debug_support as debug_ops
from .. import project as project_ops
from .. import state as state_store
from .. import svd as svd_ops


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
        cubeprogrammer_dir = None
        if cubeprogrammer_path:
            cubeprogrammer_dir = str(Path(cubeprogrammer_path).resolve().parent)
        else:
            cubeprogrammer = project_ops.resolve_executable("stm32_programmer_cli", "STM32_PROGRAMMER_CLI")
            if cubeprogrammer:
                cubeprogrammer_dir = str(Path(cubeprogrammer).resolve().parent)
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

        payload = {
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
                "server_log": state_store.compact_path(str(server_log)),
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


def step_debug_session(project: project_ops.ProjectConfig, *, instruction: bool = True) -> None:
    step_command = "stepi" if instruction else "step"
    resolved_workspace = project_ops.require_path(project.workspace, "workspace is required")
    with state_store.session_command_lock(resolved_workspace, action="debug_step"):
        resolved_workspace, session = debug_ops.resolve_session(project)
        completed = debug_ops.session_gdb_command(project, ["monitor halt", step_command, "bt"])
        source = debug_ops.extract_source_location(completed.stdout)
        state_store.update_session_state(
            resolved_workspace,
            session=session,
            status="halted",
            action="debug_step",
            source=source,
            summary=f"Single step completed at {source.get('symbol', 'unknown location')}.",
        )
        state_store.append_observation(
            resolved_workspace,
            {
                "kind": "debug_step",
                "mode": step_command,
                "source": source,
                "raw_excerpt": debug_ops.trim_lines(completed.stdout),
            },
        )
        state_store.append_verification(
            resolved_workspace,
            action="debug_step",
            ok=True,
            summary=f"Single step completed at {source.get('symbol', 'unknown location')}.",
            verification_status="hardware_verified",
            evidence={"session_path": state_store.compact_path(str(state_store.session_file(resolved_workspace)))},
            state={"source": source},
        )


def continue_debug_session(project: project_ops.ProjectConfig, *, address: str | None = None) -> None:
    resolved_workspace = project_ops.require_path(project.workspace, "workspace is required")
    with state_store.session_command_lock(resolved_workspace, action="debug_continue"):
        resolved_workspace, session = debug_ops.resolve_session(project)
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
    resolved_workspace = project_ops.require_path(project.workspace, "workspace is required")
    with state_store.session_command_lock(resolved_workspace, action="debug_registers"):
        resolved_workspace, session = debug_ops.resolve_session(project)
        completed = debug_ops.session_gdb_command(project, ["monitor halt", "info registers"])
        source = debug_ops.extract_source_location(completed.stdout)
        registers = debug_ops.extract_registers(completed.stdout)
        compact_registers = {key: value for key, value in registers.items() if key in {"sp", "lr", "pc", "control"}}
        state_store.update_session_state(
            resolved_workspace,
            session=session,
            status="halted",
            action="debug_registers",
            source=source,
            registers=compact_registers,
            summary=f"Registers captured at {source.get('symbol', 'unknown location')}.",
        )
        state_store.append_observation(
            resolved_workspace,
            {
                "kind": "registers",
                "source": source,
                "registers_compact": compact_registers,
                "raw_excerpt": debug_ops.trim_lines(completed.stdout),
            },
        )
        state_store.append_verification(
            resolved_workspace,
            action="debug_registers",
            ok=True,
            summary=f"Registers captured at {source.get('symbol', 'unknown location')}.",
            verification_status="hardware_verified",
            state={"source": source},
        )


def dump_backtrace(project: project_ops.ProjectConfig) -> None:
    resolved_workspace = project_ops.require_path(project.workspace, "workspace is required")
    with state_store.session_command_lock(resolved_workspace, action="debug_backtrace"):
        resolved_workspace, session = debug_ops.resolve_session(project)
        completed = debug_ops.session_gdb_command(project, ["monitor halt", "bt"])
        source = debug_ops.extract_source_location(completed.stdout)
        state_store.update_session_state(
            resolved_workspace,
            session=session,
            status="halted",
            action="debug_backtrace",
            source=source,
            summary=f"Backtrace captured at {source.get('symbol', 'unknown location')}.",
        )
        state_store.append_observation(
            resolved_workspace,
            {
                "kind": "backtrace",
                "source": source,
                "raw_excerpt": debug_ops.trim_lines(completed.stdout),
            },
        )
        state_store.append_verification(
            resolved_workspace,
            action="debug_backtrace",
            ok=True,
            summary=f"Backtrace captured at {source.get('symbol', 'unknown location')}.",
            verification_status="hardware_verified",
            state={"source": source},
        )


def emit_snapshot(
    project: project_ops.ProjectConfig,
    *,
    watch: list[str],
    svd_path: Path | None = None,
    backtrace_limit: int = 5,
    observation_limit: int = 4,
) -> None:
    if len(watch) > 3:
        raise typer.BadParameter("At most 3 --watch targets are supported per snapshot.")

    resolved_workspace = project_ops.require_path(project.workspace, "workspace is required")
    with state_store.session_command_lock(resolved_workspace, action="debug_snapshot"):
        payload = debug_ops.collect_snapshot_payload(
            project,
            resolved_workspace,
            watch_specs=watch,
            backtrace_limit=backtrace_limit,
            observation_limit=observation_limit,
            svd_path=svd_path,
        )

        if payload.get("session_active"):
            session = state_store.read_session(resolved_workspace)
            source = payload.get("current_location") or {}
            registers = payload.get("registers_compact") or {}
            state_store.update_session_state(
                resolved_workspace,
                session=session,
                status="halted",
                action="debug_snapshot",
                source=source if isinstance(source, dict) else None,
                registers=registers if isinstance(registers, dict) else None,
                summary=f"Snapshot captured at {source.get('symbol', 'unknown location')}.",
            )
            state_store.append_observation(
                resolved_workspace,
                {
                    "kind": "snapshot",
                    "source": source,
                    "registers_compact": registers,
                    "summary": f"Snapshot captured with {len(payload.get('peripheral_summary', []))} peripheral summary item(s).",
                    "raw_excerpt": payload.get("top_backtrace", []),
                },
            )
            state_store.append_verification(
                resolved_workspace,
                action="debug_snapshot",
                ok=True,
                summary=f"Snapshot captured at {source.get('symbol', 'unknown location')}.",
                verification_status="hardware_verified",
                state={
                    "source": source,
                    "watch_count": len(watch),
                    "observation_count": len(payload.get("recent_observations", [])),
                },
            )
            payload["verification"] = state_store.latest_verification_entry(resolved_workspace)

        typer.echo(json.dumps(payload, indent=2, ensure_ascii=False))


def read_peripheral(
    project: project_ops.ProjectConfig,
    *,
    peripheral: str,
    register: str | None = None,
    svd_path: Path | None = None,
    limit: int = 8,
) -> None:
    resolved_workspace = project_ops.require_path(project.workspace, "workspace is required")
    with state_store.session_command_lock(resolved_workspace, action="debug_peripheral_read"):
        resolved_workspace, session = debug_ops.resolve_session(project)
        resolved_svd_path = svd_ops.resolve_svd_path(resolved_workspace, svd_path)
        peripheral_name, base_address, registers = svd_ops.load_svd_peripheral(resolved_svd_path, peripheral)
        selected = registers
        if register is not None:
            target = register.upper()
            selected = [item for item in registers if item.name.upper() == target]
            if not selected:
                raise typer.BadParameter(
                    f"Register {register} not found under peripheral {peripheral_name} in {resolved_svd_path.name}"
                )
        else:
            selected = registers[:limit]

        decoded: list[dict[str, object]] = []
        for item in selected:
            address = base_address + item.address_offset
            value, raw_output = debug_ops.read_memory_word(project, resolved_workspace, address)
            fields = svd_ops.summarize_register_fields(item, value)
            decoded.append(
                {
                    "name": item.name,
                    "address": f"0x{address:08x}",
                    "value": value,
                    "value_hex": f"0x{value:08x}",
                    "fields": fields,
                    "raw_excerpt": debug_ops.trim_lines(raw_output, limit=4),
                }
            )

        summary = f"Decoded {len(decoded)} register(s) for {peripheral_name} using {resolved_svd_path.name}."
        typer.echo(summary)
        for item in decoded:
            typer.echo(f"{item['name']} @ {item['address']} = {item['value_hex']}")
            for field in item["fields"][:8]:
                typer.echo(
                    f"  {field['name']}[{field['bit_offset']}:{field['bit_offset'] + field['bit_width'] - 1}] = {field['value_hex']}"
                )
            if len(item["fields"]) > 8:
                typer.echo(f"  ... {len(item['fields']) - 8} more fields")

        compact = {
            "peripheral": peripheral_name,
            "registers": [
                {"name": item["name"], "address": item["address"], "value_hex": item["value_hex"]}
                for item in decoded
            ],
        }
        state_store.update_session_state(
            resolved_workspace,
            session=session,
            status="halted",
            action="debug_peripheral_read",
            summary=summary,
        )
        state_store.append_observation(
            resolved_workspace,
            {
                "kind": "peripheral_read",
                "peripheral": peripheral_name,
                "svd_path": state_store.compact_path(str(resolved_svd_path)),
                "decoded": decoded,
            },
        )
        state_store.append_verification(
            resolved_workspace,
            action="debug_peripheral_read",
            ok=True,
            summary=summary,
            verification_status="hardware_verified",
            evidence={"svd_path": state_store.compact_path(str(resolved_svd_path))},
            state=compact,
        )
