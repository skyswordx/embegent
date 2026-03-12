from __future__ import annotations

from pathlib import Path

import typer

from .. import project as project_ops
from .. import state as state_store


def run_flash(
    project: project_ops.ProjectConfig,
    *,
    backend: str | None = None,
    openocd_path: str | None = None,
    cubeprogrammer_path: str | None = None,
    dry_run: bool = False,
) -> None:
    resolved_workspace = project_ops.require_path(project.workspace, "workspace is required")
    resolved_elf = project_ops.require_path(project.elf, "elf is required")
    resolved_backend = project_ops.resolve_backend(project, backend)
    state_store.update_project_profile(project, resolved_workspace, backend=resolved_backend)
    if not resolved_elf.exists() and not dry_run:
        raise typer.BadParameter(f"ELF not found: {resolved_elf}")

    if dry_run:
        _run_flash_command(
            project,
            resolved_workspace=resolved_workspace,
            resolved_elf=resolved_elf,
            resolved_backend=resolved_backend,
            openocd_path=openocd_path,
            cubeprogrammer_path=cubeprogrammer_path,
            dry_run=True,
        )
        return

    with state_store.session_command_lock(resolved_workspace, action="flash"):
        if state_store.session_file(resolved_workspace).exists():
            raise typer.BadParameter("active debug session detected; stop the debug session before flashing")
        _run_flash_command(
            project,
            resolved_workspace=resolved_workspace,
            resolved_elf=resolved_elf,
            resolved_backend=resolved_backend,
            openocd_path=openocd_path,
            cubeprogrammer_path=cubeprogrammer_path,
            dry_run=False,
        )


def _run_flash_command(
    project: project_ops.ProjectConfig,
    *,
    resolved_workspace: Path,
    resolved_elf: Path,
    resolved_backend: str,
    openocd_path: str | None,
    cubeprogrammer_path: str | None,
    dry_run: bool,
) -> None:
    if resolved_backend == "openocd":
        resolved_interface = project_ops.resolve_interface_cfg(project.probe, project.interface_cfg)
        if not resolved_interface:
            raise typer.BadParameter("interface_cfg is required unless probe maps to a known interface")
        if not project.target_cfg:
            raise typer.BadParameter("target_cfg is required")

        openocd = openocd_path or project_ops.resolve_executable("openocd", "OPENOCD")
        if not openocd:
            raise typer.BadParameter("openocd was not found. Add it to PATH or set OPENOCD.")

        command = [
            openocd,
            "-f",
            project_ops.resolve_cfg_path(resolved_workspace, resolved_interface),
            "-f",
            project_ops.resolve_cfg_path(resolved_workspace, project.target_cfg),
            "-c",
            f"program {project_ops.openocd_quote(str(resolved_elf))} verify reset exit",
        ]
        project_ops.run_command(command, cwd=resolved_workspace, dry_run=dry_run)
        if not dry_run:
            state_store.append_verification(
                resolved_workspace,
                action="flash",
                ok=True,
                summary="Flash completed with OpenOCD.",
                verification_status="hardware_verified",
                evidence={"elf": state_store.compact_path(str(resolved_elf))},
                state={"backend": "openocd"},
            )
        return

    if resolved_backend == "stlink":
        cubeprogrammer = cubeprogrammer_path or project_ops.resolve_executable("stm32_programmer_cli", "STM32_PROGRAMMER_CLI")
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
        project_ops.run_command(command, cwd=resolved_workspace, dry_run=dry_run)
        if not dry_run:
            state_store.append_verification(
                resolved_workspace,
                action="flash",
                ok=True,
                summary="Flash completed with ST-LINK backend.",
                verification_status="hardware_verified",
                evidence={"elf": state_store.compact_path(str(resolved_elf))},
                state={"backend": "stlink"},
            )
        return

    raise typer.BadParameter(f"Unsupported backend: {resolved_backend}")
