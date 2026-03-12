from __future__ import annotations

import shutil

import typer

from ..infrastructure import project as project_ops
from ..infrastructure import state as state_store
from . import verification_service as verify_tools


def run_build(
    project: project_ops.ProjectConfig,
    *,
    target: str = "all",
    jobs: int = 0,
    configure: bool = True,
    fresh: bool = False,
    dry_run: bool = False,
) -> None:
    resolved_workspace = verify_tools.prepare_workspace(project)
    resolved_build_dir = project.build_dir or (resolved_workspace / "build")
    cmake = project_ops.resolve_executable("cmake", "CMAKE")
    if not cmake:
        raise typer.BadParameter("cmake was not found. Add it to PATH or set CMAKE.")
    if not (resolved_workspace / "CMakeLists.txt").exists():
        raise typer.BadParameter(f"CMakeLists.txt not found under {resolved_workspace}")

    if project.configure_preset:
        if fresh and resolved_build_dir.exists() and not dry_run:
            shutil.rmtree(resolved_build_dir)
        if configure:
            project_ops.run_command([cmake, "--preset", project.configure_preset], cwd=resolved_workspace, dry_run=dry_run)

        build_command = [cmake, "--build", "--preset", project.build_preset or project.configure_preset]
        if target != "all":
            build_command.extend(["--target", target])
        if jobs > 0:
            build_command.extend(["-j", str(jobs)])
        project_ops.run_command(build_command, cwd=resolved_workspace, dry_run=dry_run)
        if not dry_run:
            state_store.append_verification(
                resolved_workspace,
                action="build",
                ok=True,
                summary="Build completed with CMake preset.",
                verification_status="cli_verified",
                state={"build_dir": state_store.compact_path(str(resolved_build_dir))},
            )
        return

    if configure:
        if fresh and resolved_build_dir.exists() and not dry_run:
            shutil.rmtree(resolved_build_dir)
        configure_command = [cmake, "-S", str(resolved_workspace), "-B", str(resolved_build_dir)]
        resolved_generator = project.generator or (project_ops.resolve_executable("ninja", "NINJA") and "Ninja")
        if resolved_generator:
            configure_command.extend(["-G", resolved_generator])
        configure_command.extend(project.configure_args)
        project_ops.run_command(configure_command, dry_run=dry_run)

    command = [cmake, "--build", str(resolved_build_dir), "--target", target]
    if jobs > 0:
        command.extend(["-j", str(jobs)])
    project_ops.run_command(command, cwd=resolved_workspace, dry_run=dry_run)
    if not dry_run:
        state_store.append_verification(
            resolved_workspace,
            action="build",
            ok=True,
            summary="Build completed with direct CMake invocation.",
            verification_status="cli_verified",
            state={"build_dir": state_store.compact_path(str(resolved_build_dir))},
        )
