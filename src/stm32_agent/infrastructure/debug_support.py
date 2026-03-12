from __future__ import annotations

import os
import re
import subprocess
import time
from pathlib import Path
from typing import Any

import typer

from . import project as project_ops
from . import state as state_store
from . import svd as svd_ops


def extract_source_location(text: str) -> dict[str, Any]:
    pattern = re.compile(r"^(?P<symbol>.+?)\s*\(.*?\)\s+at\s+(?P<file>.+?):(?P<line>\d+)$", re.MULTILINE)
    match = pattern.search(text)
    if not match:
        return {}
    return {
        "symbol": match.group("symbol").strip(),
        "file": state_store.compact_path(match.group("file").strip()),
        "line": int(match.group("line")),
    }


def extract_registers(text: str) -> dict[str, str]:
    registers: dict[str, str] = {}
    for line in text.splitlines():
        match = re.match(
            r"^(r\d+|sp|lr|pc|xpsr|fpscr|msp|psp|primask|basepri|faultmask|control)\s+(\S+)",
            line.strip(),
        )
        if match:
            registers[match.group(1)] = match.group(2)
    return registers


def extract_backtrace_lines(text: str, limit: int = 5) -> list[str]:
    frames: list[str] = []
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped.startswith("#"):
            continue
        if frames and frames[-1] == stripped:
            continue
        frames.append(stripped)
        if len(frames) >= limit:
            break
    return frames


def trim_lines(text: str, limit: int = 20) -> list[str]:
    lines = [line for line in text.splitlines() if line.strip()]
    return lines[-limit:]


def parse_snapshot_watch(spec: str) -> tuple[str, str | None]:
    raw = spec.strip()
    if not raw:
        raise typer.BadParameter("snapshot watch target cannot be empty")
    if ":" in raw:
        peripheral, register = raw.split(":", 1)
        peripheral = peripheral.strip()
        register = register.strip()
        if not peripheral or not register:
            raise typer.BadParameter(f"invalid watch target: {spec}. Expected PERIPHERAL:REGISTER")
        return peripheral, register
    return raw, None


def terminate_pid(pid: int) -> None:
    if os.name == "nt":
        subprocess.run(
            ["taskkill", "/PID", str(pid), "/T", "/F"],
            check=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
    else:
        os.kill(pid, 15)


def run_gdb_batch(
    gdb: str,
    elf: Path,
    gdb_port: int,
    commands: list[str],
    cwd: Path | None = None,
    *,
    echo_output: bool = True,
) -> subprocess.CompletedProcess[str]:
    gdb_command = [gdb, "--quiet", "--batch", str(elf)]
    gdb_command.extend(["-ex", "set confirm off"])
    gdb_command.extend(["-ex", f"target extended-remote localhost:{gdb_port}"])
    for item in commands:
        gdb_command.extend(["-ex", item])
    gdb_command.extend(["-ex", "quit"])
    completed = subprocess.run(
        gdb_command,
        cwd=str(cwd) if cwd else None,
        text=True,
        capture_output=True,
        encoding="utf-8",
        errors="replace",
    )
    if echo_output and completed.stdout:
        project_ops.safe_echo(completed.stdout.rstrip())
    if completed.returncode != 0:
        if echo_output and completed.stderr:
            project_ops.safe_echo(completed.stderr.rstrip(), err=True)
        raise typer.Exit(completed.returncode)
    if echo_output and completed.stderr:
        project_ops.safe_echo(completed.stderr.rstrip(), err=True)
    return completed


def resolve_session(
    project: project_ops.ProjectConfig,
    workspace: Path | None = None,
) -> tuple[Path, dict[str, Any]]:
    resolved_workspace = project_ops.require_path(workspace or project.workspace, "workspace is required")
    return resolved_workspace, state_store.read_session(resolved_workspace)


def require_gdb() -> str:
    gdb = project_ops.resolve_executable("arm-none-eabi-gdb", "ARM_NONE_EABI_GDB")
    if not gdb:
        raise typer.BadParameter("arm-none-eabi-gdb was not found. Add it to PATH or set ARM_NONE_EABI_GDB.")
    return gdb


def session_gdb_command(
    project: project_ops.ProjectConfig,
    commands: list[str],
    *,
    workspace: Path | None = None,
    echo_output: bool = True,
) -> subprocess.CompletedProcess[str]:
    resolved_workspace, session = resolve_session(project, workspace)
    return run_gdb_batch(
        require_gdb(),
        Path(session["elf"]),
        int(session["gdb_port"]),
        commands,
        cwd=resolved_workspace,
        echo_output=echo_output,
    )


def read_memory_word(
    project: project_ops.ProjectConfig,
    workspace: Path,
    address: int,
    *,
    echo_output: bool = True,
) -> tuple[int, str]:
    completed = session_gdb_command(
        project,
        ["monitor halt", f"x/1wx 0x{address:08x}"],
        workspace=workspace,
        echo_output=echo_output,
    )
    pattern = re.compile(r"0x[0-9a-fA-F]+:\s+0x([0-9a-fA-F]+)")
    match = pattern.search(completed.stdout)
    if not match:
        raise typer.BadParameter(f"Failed to parse memory value at 0x{address:08x}")
    value = int(match.group(1), 16)
    return value, completed.stdout


def read_peripheral_snapshot(
    project: project_ops.ProjectConfig,
    workspace: Path,
    *,
    watch_specs: list[str],
    svd_path: Path | None = None,
    echo_output: bool = True,
) -> list[dict[str, Any]]:
    if not watch_specs:
        return []

    resolved_svd_path = svd_ops.resolve_svd_path(workspace, svd_path)
    decoded: list[dict[str, Any]] = []
    for spec in watch_specs:
        peripheral, register_name = parse_snapshot_watch(spec)
        peripheral_name, base_address, registers = svd_ops.load_svd_peripheral(resolved_svd_path, peripheral)
        selected = registers
        if register_name is not None:
            target = register_name.upper()
            selected = [item for item in registers if item.name.upper() == target]
            if not selected:
                raise typer.BadParameter(
                    f"Register {register_name} not found under peripheral {peripheral_name} in {resolved_svd_path.name}"
                )
        else:
            selected = registers[:1]

        for item in selected[:1]:
            address = base_address + item.address_offset
            value, _ = read_memory_word(project, workspace, address, echo_output=echo_output)
            fields = svd_ops.summarize_register_fields(item, value)
            decoded.append(
                {
                    "peripheral": peripheral_name,
                    "register": item.name,
                    "address": f"0x{address:08x}",
                    "value": value,
                    "value_hex": f"0x{value:08x}",
                    "fields": fields[:8],
                }
            )
    return decoded


def collect_snapshot_payload(
    project: project_ops.ProjectConfig,
    workspace: Path,
    *,
    watch_specs: list[str],
    backtrace_limit: int,
    observation_limit: int,
    svd_path: Path | None = None,
    agent_context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    context_payload = agent_context or {}
    payload: dict[str, Any] = {
        "workspace": state_store.compact_path(str(workspace)),
        "captured_at": int(time.time()),
        "session_active": False,
        "current_location": {},
        "registers_compact": {},
        "top_backtrace": [],
        "peripheral_summary": [],
        "session_state": context_payload.get("session_state", {}),
        "recent_observations": context_payload.get("recent_observations", []),
        "verification": context_payload.get("latest_verification", {}),
    }

    session_path = state_store.session_file(workspace)
    if not session_path.exists():
        return payload

    session = state_store.read_session(workspace)
    completed = session_gdb_command(
        project,
        ["monitor halt", "frame", "info registers sp lr pc control", "bt"],
        workspace=workspace,
        echo_output=False,
    )
    source = extract_source_location(completed.stdout)
    registers = extract_registers(completed.stdout)
    backtrace = extract_backtrace_lines(completed.stdout, limit=backtrace_limit)
    peripheral_summary = read_peripheral_snapshot(
        project,
        workspace,
        watch_specs=watch_specs,
        svd_path=svd_path,
        echo_output=False,
    )

    payload.update(
        {
            "session_active": True,
            "session_state": state_store.read_session_state(workspace),
            "session": {
                "backend": session.get("backend"),
                "gdb_port": session.get("gdb_port"),
                "server_kind": session.get("server_kind"),
                "started_at": session.get("started_at"),
            },
            "current_location": source,
            "registers_compact": {
                key: value for key, value in registers.items() if key in {"pc", "lr", "sp", "control"}
            },
            "top_backtrace": backtrace,
            "peripheral_summary": peripheral_summary,
        }
    )
    return payload
