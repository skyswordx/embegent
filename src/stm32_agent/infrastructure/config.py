from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import typer
import yaml


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


def _resolve_optional_path(raw: str | None, *, base: Path | None = None) -> Path | None:
    if not raw:
        return None
    path = Path(raw).expanduser()
    if base is not None and not path.is_absolute():
        path = (base / path).resolve()
    return path


def load_config(config: Path | None) -> ProjectConfig:
    if config is None:
        return ProjectConfig()

    config = config.resolve()
    data = read_yaml(config)
    config_root = config.parent
    workspace = _resolve_optional_path(data.get("workspace"), base=config_root)
    build_dir = _resolve_optional_path(data.get("build_dir"), base=workspace)
    elf = _resolve_optional_path(data.get("elf"), base=workspace)

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
