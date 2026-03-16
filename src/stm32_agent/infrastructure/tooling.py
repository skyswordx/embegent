from __future__ import annotations

import os
import shutil
from pathlib import Path

import typer

from .config import ProjectConfig

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
    return "{" + value.replace("\\", "/") + "}"


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
