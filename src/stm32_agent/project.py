from __future__ import annotations

import os
import shutil
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import typer
import yaml

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
    "D:/dap/openocd-20240916/OpenOCD-20240916-0.12.0/bin/openocd.exe",
)

COMMON_STLINK_GDB_SERVER_HINTS = (
    "D:/STM32CubeCLT_1.19.0/STLink-gdb-server/bin/ST-LINK_gdbserver.exe",
    "C:/ST/STM32CubeCLT_1.19.0/STLink-gdb-server/bin/ST-LINK_gdbserver.exe",
)

COMMON_CUBEPROGRAMMER_HINTS = (
    "D:/STM32CubeCLT_1.19.0/STM32CubeProgrammer/bin/STM32_Programmer_CLI.exe",
    "C:/ST/STM32CubeCLT_1.19.0/STM32CubeProgrammer/bin/STM32_Programmer_CLI.exe",
)


@dataclass(slots=True)
class ProjectConfig:
    config_path: Path | None = None
    project_name: str | None = None
    workspace: Path | None = None
    build_dir: Path | None = None
    elf: Path | None = None
    probe: str | None = None
    interface_cfg: str | None = None
    target_cfg: str | None = None
    serial_port: str | None = None
    baudrate: int | None = None
    generator: str | None = None
    configure_args: list[str] = field(default_factory=list)
    gdb_port: int | None = None
    openocd_args: list[str] = field(default_factory=list)
    backend: str | None = None
    stlink_gdb_server_args: list[str] = field(default_factory=list)
    serial_number: str | None = None
    frequency_khz: int | None = None
    configure_preset: str | None = None
    build_preset: str | None = None


def read_yaml(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        data = yaml.safe_load(handle) or {}
    if not isinstance(data, dict):
        raise typer.BadParameter(f"Config file must contain a mapping: {path}")
    return data


def load_config(config: Path | None) -> ProjectConfig:
    if config is None:
        return ProjectConfig()

    config = config.resolve()
    data = read_yaml(config)
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
        configure_preset=data.get("configure_preset"),
        build_preset=data.get("build_preset"),
    )


def merge_config(
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
    configure_preset: str | None = None,
    build_preset: str | None = None,
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
        probe=probe or config.probe,
        interface_cfg=interface_cfg or config.interface_cfg,
        target_cfg=target_cfg or config.target_cfg,
        serial_port=config.serial_port,
        baudrate=config.baudrate,
        generator=generator or config.generator,
        configure_args=configure_args if configure_args is not None else config.configure_args,
        gdb_port=gdb_port or config.gdb_port,
        openocd_args=openocd_args if openocd_args is not None else config.openocd_args,
        backend=backend or config.backend,
        stlink_gdb_server_args=(
            stlink_gdb_server_args
            if stlink_gdb_server_args is not None
            else config.stlink_gdb_server_args
        ),
        serial_number=serial_number or config.serial_number,
        frequency_khz=frequency_khz or config.frequency_khz,
        configure_preset=configure_preset or config.configure_preset,
        build_preset=build_preset or config.build_preset,
    )


def require_path(value: Path | None, message: str) -> Path:
    if value is None:
        raise typer.BadParameter(message)
    return value


def resolve_interface_cfg(probe: str | None, interface_cfg: str | None) -> str | None:
    if interface_cfg:
        return interface_cfg
    if probe:
        return PROBE_INTERFACE_MAP.get(probe.lower(), interface_cfg)
    return interface_cfg


def resolve_cfg_path(workspace: Path, cfg: str) -> str:
    candidate = Path(cfg)
    if candidate.is_absolute():
        return str(candidate)
    workspace_candidate = workspace / candidate
    if workspace_candidate.exists():
        return str(workspace_candidate)
    return cfg


def openocd_quote(value: str) -> str:
    normalized = value.replace("\\", "/")
    return "{" + normalized + "}"


def resolve_executable(name: str, env_var: str | None = None) -> str | None:
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


def resolve_backend(config: ProjectConfig, backend: str | None = None) -> str:
    resolved = (backend or config.backend or "openocd").strip().lower()
    aliases = {
        "stlink-gdb-server": "stlink",
        "stlink_gdb_server": "stlink",
        "st-link": "stlink",
    }
    return aliases.get(resolved, resolved)


def safe_echo(text: str, *, err: bool = False) -> None:
    stream = sys.stderr if err else sys.stdout
    encoding = getattr(stream, "encoding", None) or "utf-8"
    normalized = text.encode(encoding, errors="replace").decode(encoding, errors="replace")
    typer.echo(normalized, err=err)


def run_command(
    command: list[str],
    cwd: Path | None = None,
    dry_run: bool = False,
) -> subprocess.CompletedProcess[str] | None:
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
        safe_echo(completed.stdout.rstrip())
    if completed.returncode != 0:
        if completed.stderr:
            safe_echo(completed.stderr.rstrip(), err=True)
        raise typer.Exit(completed.returncode)
    if completed.stderr:
        safe_echo(completed.stderr.rstrip(), err=True)
    return completed


def doctor_checks(config: ProjectConfig) -> list[tuple[str, str]]:
    workspace = config.workspace
    interface_cfg = resolve_interface_cfg(config.probe, config.interface_cfg)
    target_cfg = config.target_cfg
    checks = [
        ("cmake", resolve_executable("cmake", "CMAKE")),
        ("ninja", resolve_executable("ninja", "NINJA")),
        ("arm-none-eabi-gcc", resolve_executable("arm-none-eabi-gcc", "ARM_NONE_EABI_GCC")),
        ("arm-none-eabi-gdb", resolve_executable("arm-none-eabi-gdb", "ARM_NONE_EABI_GDB")),
        ("openocd", resolve_executable("openocd", "OPENOCD")),
        ("stlink_gdbserver", resolve_executable("stlink_gdbserver", "STLINK_GDB_SERVER")),
        ("stm32_programmer_cli", resolve_executable("stm32_programmer_cli", "STM32_PROGRAMMER_CLI")),
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


def doctor_required_keys(config: ProjectConfig) -> set[str]:
    backend = resolve_backend(config)
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
