from __future__ import annotations

import os
import json
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any
import time

import typer
import yaml

app = typer.Typer(help="STM32 AI debug-chain CLI prototype.")
debug_app = typer.Typer(help="Debug-related commands.")
app.add_typer(debug_app, name="debug")

PROBE_INTERFACE_MAP = {
    "stlink": "interface/stlink.cfg",
    "daplink": "interface/cmsis-dap.cfg",
    "cmsis-dap": "interface/cmsis-dap.cfg",
}
COMMON_OPENOCD_HINTS = (
    "D:/OpenOCD/bin/openocd.exe",
    "C:/OpenOCD/bin/openocd.exe",
    "D:/xpack-openocd/bin/openocd.exe",
    "C:/xpack-openocd/bin/openocd.exe",
    "D:/ST/OpenOCD/bin/openocd.exe",
    "C:/ST/OpenOCD/bin/openocd.exe",
)
COMMON_STLINK_GDB_SERVER_HINTS = (
    "D:/STM32CubeCLT_1.19.0/STLink-gdb-server/bin/ST-LINK_gdbserver.exe",
    "C:/ST/STM32CubeCLT_1.19.0/STLink-gdb-server/bin/ST-LINK_gdbserver.exe",
)
COMMON_CUBEPROGRAMMER_HINTS = (
    "D:/STM32CubeCLT_1.19.0/STM32CubeProgrammer/bin/STM32_Programmer_CLI.exe",
    "C:/ST/STM32CubeCLT_1.19.0/STM32CubeProgrammer/bin/STM32_Programmer_CLI.exe",
)


@dataclass
class ProjectConfig:
    config_path: Path | None
    project_name: str | None
    workspace: Path | None
    build_dir: Path | None
    elf: Path | None
    probe: str | None
    interface_cfg: str | None
    target_cfg: str | None
    serial_port: str | None
    baudrate: int | None
    generator: str | None
    configure_args: list[str]
    gdb_port: int | None
    openocd_args: list[str]
    backend: str | None
    stlink_gdb_server_args: list[str]
    serial_number: str | None
    frequency_khz: int | None


def _read_yaml(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        data = yaml.safe_load(handle) or {}
    if not isinstance(data, dict):
        raise typer.BadParameter(f"Config file must contain a mapping: {path}")
    return data


def _load_config(config: Path | None) -> ProjectConfig:
    if config is None:
        return ProjectConfig(None, None, None, None, None, None, None, None, None, None, None, [], None, [], None, [], None, None)

    config = config.resolve()
    data = _read_yaml(config)
    config_root = config.parent

    workspace = Path(data["workspace"]).expanduser() if data.get("workspace") else None
    if workspace is not None and not workspace.is_absolute():
        workspace = (config_root / workspace).resolve()
    build_dir_raw = data.get("build_dir")
    build_dir = Path(build_dir_raw) if build_dir_raw else None
    if build_dir is not None and workspace is not None and not build_dir.is_absolute():
        build_dir = workspace / build_dir

    elf_raw = data.get("elf")
    elf = Path(elf_raw) if elf_raw else None
    if elf is not None and workspace is not None and not elf.is_absolute():
        elf = workspace / elf

    return ProjectConfig(
        config_path=config,
        project_name=data.get("project_name"),
        workspace=workspace,
        build_dir=build_dir,
        elf=elf,
        probe=data.get("probe"),
        interface_cfg=data.get("interface_cfg"),
        target_cfg=data.get("target_cfg"),
        serial_port=data.get("serial_port"),
        baudrate=int(data["baudrate"]) if data.get("baudrate") is not None else None,
        generator=data.get("generator"),
        configure_args=[str(item) for item in data.get("configure_args", [])],
        gdb_port=int(data["gdb_port"]) if data.get("gdb_port") is not None else None,
        openocd_args=[str(item) for item in data.get("openocd_args", [])],
        backend=data.get("backend"),
        stlink_gdb_server_args=[str(item) for item in data.get("stlink_gdb_server_args", [])],
        serial_number=data.get("serial_number"),
        frequency_khz=int(data["frequency_khz"]) if data.get("frequency_khz") is not None else None,
    )


def _merge_config(
    config: ProjectConfig,
    *,
    workspace: Path | None = None,
    build_dir: Path | None = None,
    elf: Path | None = None,
    probe: str | None = None,
    interface_cfg: str | None = None,
    target_cfg: str | None = None,
    generator: str | None = None,
    configure_args: list[str] | None = None,
    gdb_port: int | None = None,
    openocd_args: list[str] | None = None,
    backend: str | None = None,
    stlink_gdb_server_args: list[str] | None = None,
    serial_number: str | None = None,
    frequency_khz: int | None = None,
) -> ProjectConfig:
    merged_workspace = workspace or config.workspace
    merged_build_dir = build_dir or config.build_dir
    if merged_build_dir is not None and merged_workspace is not None and not merged_build_dir.is_absolute():
        merged_build_dir = merged_workspace / merged_build_dir

    merged_elf = elf or config.elf
    if merged_elf is not None and merged_workspace is not None and not merged_elf.is_absolute():
        merged_elf = merged_workspace / merged_elf

    return ProjectConfig(
        config_path=config.config_path,
        project_name=config.project_name,
        workspace=merged_workspace,
        build_dir=merged_build_dir,
        elf=merged_elf,
        probe=(probe or config.probe),
        interface_cfg=(interface_cfg or config.interface_cfg),
        target_cfg=(target_cfg or config.target_cfg),
        serial_port=config.serial_port,
        baudrate=config.baudrate,
        generator=(generator or config.generator),
        configure_args=(configure_args if configure_args is not None else config.configure_args),
        gdb_port=(gdb_port or config.gdb_port),
        openocd_args=(openocd_args if openocd_args is not None else config.openocd_args),
        backend=(backend or config.backend),
        stlink_gdb_server_args=(
            stlink_gdb_server_args if stlink_gdb_server_args is not None else config.stlink_gdb_server_args
        ),
        serial_number=(serial_number or config.serial_number),
        frequency_khz=(frequency_khz or config.frequency_khz),
    )


def _require_path(value: Path | None, message: str) -> Path:
    if value is None:
        raise typer.BadParameter(message)
    return value


def _resolve_interface_cfg(probe: str | None, interface_cfg: str | None) -> str | None:
    if interface_cfg:
        return interface_cfg
    if probe:
        return PROBE_INTERFACE_MAP.get(probe.lower(), interface_cfg)
    return interface_cfg


def _resolve_cfg_path(workspace: Path, cfg: str) -> str:
    candidate = Path(cfg)
    if candidate.is_absolute():
        return str(candidate)
    return str(workspace / candidate)


def _resolve_executable(name: str, env_var: str | None = None) -> str | None:
    env_value = os.environ.get(env_var) if env_var else None
    if env_value and Path(env_value).exists():
        return env_value

    found = shutil.which(name)
    if found:
        return found

    if name == "openocd":
        for candidate in COMMON_OPENOCD_HINTS:
            if Path(candidate).exists():
                return candidate
    if name == "stlink_gdbserver":
        for candidate in COMMON_STLINK_GDB_SERVER_HINTS:
            if Path(candidate).exists():
                return candidate
    if name == "stm32_programmer_cli":
        for candidate in COMMON_CUBEPROGRAMMER_HINTS:
            if Path(candidate).exists():
                return candidate
    return None


def _resolve_backend(config: ProjectConfig, backend: str | None = None) -> str:
    resolved = (backend or config.backend or "openocd").strip().lower()
    aliases = {
        "stlink-gdb-server": "stlink",
        "stlink_gdb_server": "stlink",
        "st-link": "stlink",
    }
    return aliases.get(resolved, resolved)


def _run_command(command: list[str], cwd: Path | None = None, dry_run: bool = False) -> subprocess.CompletedProcess[str] | None:
    typer.echo("$ " + " ".join(command))
    if dry_run:
        return None

    completed = subprocess.run(
        command,
        cwd=str(cwd) if cwd else None,
        text=True,
        capture_output=True,
        encoding="utf-8",
        errors="replace",
    )
    if completed.stdout:
        typer.echo(completed.stdout.rstrip())
    if completed.returncode != 0:
        if completed.stderr:
            typer.echo(completed.stderr.rstrip(), err=True)
        raise typer.Exit(completed.returncode)
    if completed.stderr:
        typer.echo(completed.stderr.rstrip(), err=True)
    return completed


def _state_dir(workspace: Path) -> Path:
    return workspace / ".stm32-agent"


def _logs_dir(workspace: Path) -> Path:
    return _state_dir(workspace) / "logs"


def _session_file(workspace: Path) -> Path:
    return _state_dir(workspace) / "session.json"


def _ensure_state_dirs(workspace: Path) -> None:
    _logs_dir(workspace).mkdir(parents=True, exist_ok=True)


def _write_session(workspace: Path, payload: dict[str, Any]) -> None:
    _ensure_state_dirs(workspace)
    _session_file(workspace).write_text(json.dumps(payload, indent=2), encoding="utf-8")


def _read_session(workspace: Path) -> dict[str, Any]:
    session_path = _session_file(workspace)
    if not session_path.exists():
        raise typer.BadParameter(f"session file not found: {session_path}")
    return json.loads(session_path.read_text(encoding="utf-8"))


def _remove_session(workspace: Path) -> None:
    session_path = _session_file(workspace)
    if session_path.exists():
        session_path.unlink()


def _terminate_pid(pid: int) -> None:
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


def _run_gdb_batch(gdb: str, elf: Path, gdb_port: int, commands: list[str], cwd: Path | None = None) -> subprocess.CompletedProcess[str]:
    gdb_command = [gdb, "--quiet", str(elf)]
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
    if completed.stdout:
        typer.echo(completed.stdout.rstrip())
    if completed.returncode != 0:
        if completed.stderr:
            typer.echo(completed.stderr.rstrip(), err=True)
        raise typer.Exit(completed.returncode)
    if completed.stderr:
        typer.echo(completed.stderr.rstrip(), err=True)
    return completed


def _doctor_checks(config: ProjectConfig) -> list[tuple[str, str]]:
    workspace = config.workspace
    interface_cfg = _resolve_interface_cfg(config.probe, config.interface_cfg)
    target_cfg = config.target_cfg
    checks = [
        ("cmake", _resolve_executable("cmake", "CMAKE")),
        ("ninja", _resolve_executable("ninja", "NINJA")),
        ("arm-none-eabi-gcc", _resolve_executable("arm-none-eabi-gcc", "ARM_NONE_EABI_GCC")),
        ("arm-none-eabi-gdb", _resolve_executable("arm-none-eabi-gdb", "ARM_NONE_EABI_GDB")),
        ("openocd", _resolve_executable("openocd", "OPENOCD")),
        ("stlink_gdbserver", _resolve_executable("stlink_gdbserver", "STLINK_GDB_SERVER")),
        ("stm32_programmer_cli", _resolve_executable("stm32_programmer_cli", "STM32_PROGRAMMER_CLI")),
    ]
    results: list[tuple[str, str]] = []
    for name, path in checks:
        results.append((name, path or "MISSING"))

    if workspace is not None:
        results.append(("workspace", "OK" if workspace.exists() else f"MISSING: {workspace}"))
        results.append(
            (
                "CMakeLists.txt",
                "OK" if (workspace / "CMakeLists.txt").exists() else f"MISSING: {workspace / 'CMakeLists.txt'}",
            )
        )
        if interface_cfg:
            results.append(
                (
                    "interface_cfg",
                    "OK" if (workspace / interface_cfg).exists() else f"CHECK: {workspace / interface_cfg}",
                )
            )
        if target_cfg:
            results.append(
                (
                    "target_cfg",
                    "OK" if (workspace / target_cfg).exists() else f"CHECK: {workspace / target_cfg}",
                )
            )
        if config.elf:
            results.append(("elf", "OK" if config.elf.exists() else f"CHECK: {config.elf}"))
    return results


def _doctor_required_keys(config: ProjectConfig) -> set[str]:
    backend = _resolve_backend(config)
    required = {
        "cmake",
        "ninja",
        "arm-none-eabi-gcc",
        "arm-none-eabi-gdb",
    }
    if backend == "openocd":
        required.add("openocd")
    elif backend == "stlink":
        required.add("stlink_gdbserver")
        required.add("stm32_programmer_cli")
    return required


@app.command()
def doctor(
    config: Path | None = typer.Option(None, "--config", "-c", help="Path to a YAML project config."),
) -> None:
    """Check required tools and project paths."""
    project = _load_config(config)
    typer.echo(f"{'backend':18} {_resolve_backend(project)}")
    ok = True
    required_keys = _doctor_required_keys(project)
    for name, result in _doctor_checks(project):
        typer.echo(f"{name:18} {result}")
        if name in required_keys and (result == "MISSING" or result.startswith("MISSING:")):
            ok = False

    if not ok:
        raise typer.Exit(1)


@app.command()
def build(
    config: Path | None = typer.Option(None, "--config", "-c", help="Path to a YAML project config."),
    workspace: Path | None = typer.Option(None, help="STM32 project root containing CMakeLists.txt."),
    build_dir: Path | None = typer.Option(None, help="Build directory."),
    target: str = typer.Option("all", help="CMake build target."),
    jobs: int = typer.Option(0, min=0, help="Parallel build jobs. 0 means use CMake default."),
    generator: str | None = typer.Option(None, help="CMake generator, for example Ninja."),
    configure_arg: list[str] | None = typer.Option(None, "--configure-arg", help="Extra configure arguments."),
    configure: bool = typer.Option(True, help="Run CMake configure before building."),
    fresh: bool = typer.Option(False, help="Remove the build directory before configuring."),
    dry_run: bool = typer.Option(False, help="Print commands only."),
) -> None:
    """Build the current STM32 project with CMake."""
    project = _merge_config(
        _load_config(config),
        workspace=workspace,
        build_dir=build_dir,
        generator=generator,
        configure_args=configure_arg,
    )
    resolved_workspace = _require_path(project.workspace, "workspace is required")
    resolved_build_dir = project.build_dir or (resolved_workspace / "build")
    cmake = _resolve_executable("cmake", "CMAKE")
    if not cmake:
        raise typer.BadParameter("cmake was not found. Add it to PATH or set CMAKE.")
    if not (resolved_workspace / "CMakeLists.txt").exists():
        raise typer.BadParameter(f"CMakeLists.txt not found under {resolved_workspace}")

    if configure:
        if fresh and resolved_build_dir.exists() and not dry_run:
            shutil.rmtree(resolved_build_dir)
        configure_command = [cmake, "-S", str(resolved_workspace), "-B", str(resolved_build_dir)]
        resolved_generator = project.generator or (_resolve_executable("ninja", "NINJA") and "Ninja")
        if resolved_generator:
            configure_command.extend(["-G", resolved_generator])
        configure_command.extend(project.configure_args)
        _run_command(configure_command, dry_run=dry_run)

    command = [cmake, "--build", str(resolved_build_dir), "--target", target]
    if jobs > 0:
        command.extend(["-j", str(jobs)])
    _run_command(command, cwd=resolved_workspace, dry_run=dry_run)


@app.command()
def flash(
    config: Path | None = typer.Option(None, "--config", "-c", help="Path to a YAML project config."),
    workspace: Path | None = typer.Option(None, help="STM32 project root."),
    elf: Path | None = typer.Option(None, help="ELF path."),
    probe: str | None = typer.Option(None, help="Probe type: stlink, daplink, cmsis-dap."),
    interface_cfg: str | None = typer.Option(None, help="OpenOCD interface config path."),
    target_cfg: str | None = typer.Option(None, help="OpenOCD target config path."),
    openocd_path: str | None = typer.Option(None, help="Explicit path to openocd."),
    backend: str | None = typer.Option(None, help="Flash backend: openocd or stlink."),
    stlink_gdb_server_path: str | None = typer.Option(None, help="Explicit path to ST-LINK_gdbserver."),
    cubeprogrammer_path: str | None = typer.Option(None, help="Explicit path to STM32_Programmer_CLI."),
    serial_number: str | None = typer.Option(None, help="ST-LINK serial number."),
    frequency_khz: int | None = typer.Option(None, help="SWD/JTAG frequency in kHz."),
    dry_run: bool = typer.Option(False, help="Print commands only."),
) -> None:
    """Flash ELF to target board."""
    project = _merge_config(
        _load_config(config),
        workspace=workspace,
        elf=elf,
        probe=probe,
        interface_cfg=interface_cfg,
        target_cfg=target_cfg,
        backend=backend,
        serial_number=serial_number,
        frequency_khz=frequency_khz,
    )
    resolved_workspace = _require_path(project.workspace, "workspace is required")
    resolved_elf = _require_path(project.elf, "elf is required")
    if not resolved_elf.exists() and not dry_run:
        raise typer.BadParameter(f"ELF not found: {resolved_elf}")

    resolved_backend = _resolve_backend(project, backend)
    if resolved_backend == "openocd":
        resolved_interface = _resolve_interface_cfg(project.probe, project.interface_cfg)
        if not resolved_interface:
            raise typer.BadParameter("interface_cfg is required unless probe maps to a known interface")
        if not project.target_cfg:
            raise typer.BadParameter("target_cfg is required")

        openocd = openocd_path or _resolve_executable("openocd", "OPENOCD")
        if not openocd:
            raise typer.BadParameter("openocd was not found. Add it to PATH or set OPENOCD.")

        command = [
            openocd,
            "-f",
            _resolve_cfg_path(resolved_workspace, resolved_interface),
            "-f",
            _resolve_cfg_path(resolved_workspace, project.target_cfg),
            "-c",
            f"program {resolved_elf} verify reset exit",
        ]
        _run_command(command, cwd=resolved_workspace, dry_run=dry_run)
        return

    if resolved_backend == "stlink":
        cubeprogrammer = cubeprogrammer_path or _resolve_executable("stm32_programmer_cli", "STM32_PROGRAMMER_CLI")
        if not cubeprogrammer:
            raise typer.BadParameter(
                "STM32_Programmer_CLI was not found. Add it to PATH or set STM32_PROGRAMMER_CLI."
            )
        connect_arg = "port=SWD"
        if project.serial_number:
            connect_arg += f" sn={project.serial_number}"
        if project.frequency_khz:
            connect_arg += f" freq={project.frequency_khz}"
        command = [cubeprogrammer, "-c", connect_arg, "-w", str(resolved_elf), "-v", "-rst"]
        _run_command(command, cwd=resolved_workspace, dry_run=dry_run)
        return

    raise typer.BadParameter(f"Unsupported backend: {resolved_backend}")


@app.command()
def monitor() -> None:
    """Serial monitor is not implemented yet."""
    raise typer.Exit("monitor is not implemented yet")


def _not_implemented(command_name: str) -> None:
    raise typer.Exit(f"{command_name} is not implemented yet")


@debug_app.command("start")
def debug_start(
    config: Path | None = typer.Option(None, "--config", "-c", help="Path to a YAML project config."),
    workspace: Path | None = typer.Option(None, help="STM32 project root."),
    elf: Path | None = typer.Option(None, help="ELF path."),
    probe: str | None = typer.Option(None, help="Probe type: stlink, daplink, cmsis-dap."),
    interface_cfg: str | None = typer.Option(None, help="OpenOCD interface config path."),
    target_cfg: str | None = typer.Option(None, help="OpenOCD target config path."),
    openocd_path: str | None = typer.Option(None, help="Explicit path to openocd."),
    backend: str | None = typer.Option(None, help="Debug backend: openocd or stlink."),
    stlink_gdb_server_path: str | None = typer.Option(None, help="Explicit path to ST-LINK_gdbserver."),
    cubeprogrammer_path: str | None = typer.Option(None, help="Explicit path to STM32_Programmer_CLI."),
    serial_number: str | None = typer.Option(None, help="ST-LINK serial number."),
    frequency_khz: int | None = typer.Option(None, help="SWD/JTAG frequency in kHz."),
    gdb_port: int = typer.Option(3333, help="OpenOCD GDB port."),
    dry_run: bool = typer.Option(False, help="Print commands only."),
) -> None:
    """Start a debug session."""
    project = _merge_config(
        _load_config(config),
        workspace=workspace,
        elf=elf,
        probe=probe,
        interface_cfg=interface_cfg,
        target_cfg=target_cfg,
        gdb_port=gdb_port,
        backend=backend,
        serial_number=serial_number,
        frequency_khz=frequency_khz,
    )
    resolved_workspace = _require_path(project.workspace, "workspace is required")
    resolved_elf = _require_path(project.elf, "elf is required")
    session_path = _session_file(resolved_workspace)
    if session_path.exists():
        raise typer.BadParameter(f"debug session already exists: {session_path}")

    resolved_backend = _resolve_backend(project, backend)
    interface_path = None
    target_path = None
    command: list[str]
    session_kind: str
    gdb_port_value = project.gdb_port or gdb_port
    if resolved_backend == "openocd":
        resolved_interface = _resolve_interface_cfg(project.probe, project.interface_cfg)
        if not resolved_interface:
            raise typer.BadParameter("interface_cfg is required unless probe maps to a known interface")
        if not project.target_cfg:
            raise typer.BadParameter("target_cfg is required")
        openocd = openocd_path or _resolve_executable("openocd", "OPENOCD")
        if not openocd:
            raise typer.BadParameter("openocd was not found. Add it to PATH or set OPENOCD.")
        interface_path = _resolve_cfg_path(resolved_workspace, resolved_interface)
        target_path = _resolve_cfg_path(resolved_workspace, project.target_cfg)
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
        stlink_gdbserver = stlink_gdb_server_path or _resolve_executable("stlink_gdbserver", "STLINK_GDB_SERVER")
        if not stlink_gdbserver:
            raise typer.BadParameter(
                "ST-LINK_gdbserver was not found. Add it to PATH or set STLINK_GDB_SERVER."
            )
        cubeprogrammer_dir = None
        if cubeprogrammer_path:
            cubeprogrammer_dir = str(Path(cubeprogrammer_path).resolve().parent)
        else:
            cubeprogrammer = _resolve_executable("stm32_programmer_cli", "STM32_PROGRAMMER_CLI")
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

    _ensure_state_dirs(resolved_workspace)
    timestamp = int(time.time())
    openocd_log = _logs_dir(resolved_workspace) / f"openocd-{timestamp}.log"
    with openocd_log.open("w", encoding="utf-8") as handle:
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
        log_text = openocd_log.read_text(encoding="utf-8", errors="replace") if openocd_log.exists() else ""
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
        "server_log": str(openocd_log),
        "started_at": timestamp,
    }
    _write_session(resolved_workspace, payload)
    typer.echo(f"session started: {session_path}")


@debug_app.command("stop")
def debug_stop(
    config: Path | None = typer.Option(None, "--config", "-c", help="Path to a YAML project config."),
    workspace: Path | None = typer.Option(None, help="STM32 project root."),
) -> None:
    """Stop the current debug session."""
    project = _merge_config(_load_config(config), workspace=workspace)
    resolved_workspace = _require_path(project.workspace, "workspace is required")
    session = _read_session(resolved_workspace)
    pid = int(session["server_pid"])
    _terminate_pid(pid)
    _remove_session(resolved_workspace)
    typer.echo(f"session stopped: pid={pid}")


@debug_app.command("step")
def debug_step() -> None:
    """Perform one debug step."""
    _not_implemented("debug step")


@debug_app.command("continue")
def debug_continue() -> None:
    """Continue the current debug session."""
    _not_implemented("debug continue")


@debug_app.command("registers")
def debug_registers(
    config: Path | None = typer.Option(None, "--config", "-c", help="Path to a YAML project config."),
    workspace: Path | None = typer.Option(None, help="STM32 project root."),
) -> None:
    """Dump registers from the current debug session."""
    project = _merge_config(_load_config(config), workspace=workspace)
    resolved_workspace = _require_path(project.workspace, "workspace is required")
    session = _read_session(resolved_workspace)
    gdb = _resolve_executable("arm-none-eabi-gdb", "ARM_NONE_EABI_GDB")
    if not gdb:
        raise typer.BadParameter("arm-none-eabi-gdb was not found. Add it to PATH or set ARM_NONE_EABI_GDB.")
    _run_gdb_batch(
        gdb,
        Path(session["elf"]),
        int(session["gdb_port"]),
        ["monitor reset halt", "info registers"],
        cwd=resolved_workspace,
    )


@debug_app.command("backtrace")
def debug_backtrace(
    config: Path | None = typer.Option(None, "--config", "-c", help="Path to a YAML project config."),
    workspace: Path | None = typer.Option(None, help="STM32 project root."),
) -> None:
    """Dump the current backtrace."""
    project = _merge_config(_load_config(config), workspace=workspace)
    resolved_workspace = _require_path(project.workspace, "workspace is required")
    session = _read_session(resolved_workspace)
    gdb = _resolve_executable("arm-none-eabi-gdb", "ARM_NONE_EABI_GDB")
    if not gdb:
        raise typer.BadParameter("arm-none-eabi-gdb was not found. Add it to PATH or set ARM_NONE_EABI_GDB.")
    _run_gdb_batch(
        gdb,
        Path(session["elf"]),
        int(session["gdb_port"]),
        ["monitor reset halt", "bt"],
        cwd=resolved_workspace,
    )


if __name__ == "__main__":
    app()
