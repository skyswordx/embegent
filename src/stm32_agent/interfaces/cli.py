from __future__ import annotations

from pathlib import Path

import typer

from ..application import build_service as build_tools
from ..application import debug_actions_service
from ..application import debug_session_service
from ..application import debug_snapshot_service
from ..application import flash_service as flash_tools
from ..application import monitor_service as monitor_tools
from ..infrastructure import project as project_ops
from ..infrastructure import svd as svd_ops

app = typer.Typer(help="STM32 AI debug-chain CLI prototype.")
debug_app = typer.Typer(help="Debug-related commands.")
svd_app = typer.Typer(help="CMSIS-SVD related commands.")
app.add_typer(debug_app, name="debug")
app.add_typer(svd_app, name="svd")


def _resolve_project(
    config: Path | None,
    **overrides: object,
) -> project_ops.ProjectConfig:
    return project_ops.merge_config(project_ops.load_config(config), **overrides)


@svd_app.command("fetch")
def svd_fetch(
    chip: str = typer.Option(..., help="STM32 chip model, for example STM32H750VBT6."),
    workspace: Path | None = typer.Option(None, help="STM32 project root. If omitted, use the current directory."),
    output: Path | None = typer.Option(None, help="Optional output path for the downloaded SVD."),
    force: bool = typer.Option(False, help="Overwrite existing local SVD file."),
) -> None:
    """Fetch an STM32 CMSIS-SVD file from modm-io/cmsis-svd-stm32."""
    result = svd_ops.fetch_svd(chip=chip, workspace=workspace or Path.cwd(), output=output, force=force)
    typer.echo(
        f"SVD {'reused' if result['reused'] else 'fetched'}: {result['candidate_name']} -> {result['local_path']}"
    )


@app.command()
def doctor(
    config: Path | None = typer.Option(None, "--config", "-c", help="Path to a YAML project config."),
) -> None:
    """Check required tools and project paths."""
    project = project_ops.load_config(config)
    typer.echo(f"{'backend':18} {project_ops.resolve_backend(project)}")
    ok = True
    required_keys = project_ops.doctor_required_keys(project)
    for name, result in project_ops.doctor_checks(project):
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
    configure_preset: str | None = typer.Option(None, help="CMake configure preset name."),
    build_preset: str | None = typer.Option(None, help="CMake build preset name."),
    configure_arg: list[str] | None = typer.Option(None, "--configure-arg", help="Extra configure arguments."),
    configure: bool = typer.Option(True, help="Run CMake configure before building."),
    fresh: bool = typer.Option(False, help="Remove the build directory before configuring."),
    dry_run: bool = typer.Option(False, help="Print commands only."),
) -> None:
    """Build the current STM32 project with CMake."""
    project = _resolve_project(
        config,
        workspace=workspace,
        build_dir=build_dir,
        generator=generator,
        configure_args=configure_arg,
        configure_preset=configure_preset,
        build_preset=build_preset,
    )
    build_tools.run_build(
        project,
        target=target,
        jobs=jobs,
        configure=configure,
        fresh=fresh,
        dry_run=dry_run,
    )


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
    project = _resolve_project(
        config,
        workspace=workspace,
        elf=elf,
        probe=probe,
        interface_cfg=interface_cfg,
        target_cfg=target_cfg,
        backend=backend,
        serial_number=serial_number,
        frequency_khz=frequency_khz,
    )
    flash_tools.run_flash(
        project,
        backend=backend,
        openocd_path=openocd_path,
        cubeprogrammer_path=cubeprogrammer_path,
        dry_run=dry_run,
    )


@app.command()
def monitor(
    config: Path | None = typer.Option(None, "--config", "-c", help="Path to a YAML project config."),
    workspace: Path | None = typer.Option(None, help="STM32 project root."),
    serial_port: str | None = typer.Option(None, help="Serial port, for example COM6."),
    baudrate: int | None = typer.Option(None, help="Baudrate, for example 115200."),
    duration: float = typer.Option(0.0, min=0.0, help="Read duration in seconds. 0 means until interrupted."),
    log_file: Path | None = typer.Option(None, help="Optional log file path."),
    raw: bool = typer.Option(False, help="Do not prefix lines with timestamps."),
) -> None:
    """Stream serial monitor output to stdout and optionally a log file."""
    project = _resolve_project(config, workspace=workspace)
    monitor_tools.run_monitor(
        project,
        serial_port=serial_port,
        baudrate=baudrate,
        duration=duration,
        log_file=log_file,
        raw=raw,
    )


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
    project = _resolve_project(
        config,
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
    debug_session_service.start_debug_session(
        project,
        backend=backend,
        openocd_path=openocd_path,
        stlink_gdb_server_path=stlink_gdb_server_path,
        cubeprogrammer_path=cubeprogrammer_path,
        gdb_port=gdb_port,
        dry_run=dry_run,
    )


@debug_app.command("stop")
def debug_stop(
    config: Path | None = typer.Option(None, "--config", "-c", help="Path to a YAML project config."),
    workspace: Path | None = typer.Option(None, help="STM32 project root."),
) -> None:
    """Stop the current debug session."""
    project = _resolve_project(config, workspace=workspace)
    debug_session_service.stop_debug_session(project)


@debug_app.command("step")
def debug_step(
    config: Path | None = typer.Option(None, "--config", "-c", help="Path to a YAML project config."),
    workspace: Path | None = typer.Option(None, help="STM32 project root."),
    instruction: bool = typer.Option(True, "--instruction/--source", help="Use stepi or step."),
) -> None:
    """Perform one debug step."""
    project = _resolve_project(config, workspace=workspace)
    debug_actions_service.step_debug_session(project, instruction=instruction)


@debug_app.command("continue")
def debug_continue(
    config: Path | None = typer.Option(None, "--config", "-c", help="Path to a YAML project config."),
    workspace: Path | None = typer.Option(None, help="STM32 project root."),
    address: str | None = typer.Option(None, help="Optional resume address, for example 0x08000100."),
) -> None:
    """Continue the current debug session."""
    project = _resolve_project(config, workspace=workspace)
    debug_actions_service.continue_debug_session(project, address=address)


@debug_app.command("registers")
def debug_registers(
    config: Path | None = typer.Option(None, "--config", "-c", help="Path to a YAML project config."),
    workspace: Path | None = typer.Option(None, help="STM32 project root."),
) -> None:
    """Dump registers from the current debug session."""
    project = _resolve_project(config, workspace=workspace)
    debug_actions_service.dump_registers(project)


@debug_app.command("backtrace")
def debug_backtrace(
    config: Path | None = typer.Option(None, "--config", "-c", help="Path to a YAML project config."),
    workspace: Path | None = typer.Option(None, help="STM32 project root."),
) -> None:
    """Dump the current backtrace."""
    project = _resolve_project(config, workspace=workspace)
    debug_actions_service.dump_backtrace(project)


@debug_app.command("snapshot")
def debug_snapshot(
    config: Path | None = typer.Option(None, "--config", "-c", help="Path to a YAML project config."),
    workspace: Path | None = typer.Option(None, help="STM32 project root."),
    watch: list[str] = typer.Option(
        [],
        "--watch",
        help="Peripheral snapshot target, format PERIPHERAL:REGISTER. Repeat 1-3 times.",
    ),
    svd_path: Path | None = typer.Option(None, help="Optional local SVD file path."),
    backtrace_limit: int = typer.Option(5, min=1, max=10, help="Max number of backtrace frames."),
    observation_limit: int = typer.Option(4, min=1, max=10, help="Max number of recent observations."),
) -> None:
    """Aggregate the current debug context into one Agent-friendly snapshot."""
    project = _resolve_project(config, workspace=workspace)
    debug_snapshot_service.emit_snapshot(
        project,
        watch=watch,
        svd_path=svd_path,
        backtrace_limit=backtrace_limit,
        observation_limit=observation_limit,
    )


@debug_app.command("peripheral-read")
def debug_peripheral_read(
    config: Path | None = typer.Option(None, "--config", "-c", help="Path to a YAML project config."),
    workspace: Path | None = typer.Option(None, help="STM32 project root."),
    peripheral: str = typer.Option(..., help="Peripheral name from SVD, for example RCC or GPIOB."),
    register: str | None = typer.Option(None, help="Optional register name, for example CR or MODER."),
    svd_path: Path | None = typer.Option(None, help="Optional local SVD file path."),
    limit: int = typer.Option(8, min=1, max=64, help="Max number of registers when --register is omitted."),
) -> None:
    """Read peripheral registers via GDB and decode them with a local SVD."""
    project = _resolve_project(config, workspace=workspace)
    debug_snapshot_service.read_peripheral(
        project,
        peripheral=peripheral,
        register=register,
        svd_path=svd_path,
        limit=limit,
    )


if __name__ == "__main__":
    app()
