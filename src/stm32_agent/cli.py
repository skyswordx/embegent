from __future__ import annotations

import os
import json
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any
import time
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import Request, urlopen
import xml.etree.ElementTree as ET

import serial
import typer
import yaml

app = typer.Typer(help="STM32 AI debug-chain CLI prototype.")
debug_app = typer.Typer(help="Debug-related commands.")
svd_app = typer.Typer(help="CMSIS-SVD related commands.")
app.add_typer(debug_app, name="debug")
app.add_typer(svd_app, name="svd")

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
SVD_REPO_API = "https://api.github.com/repos/modm-io/cmsis-svd-stm32/contents"
SVD_REPO_RAW = "https://raw.githubusercontent.com/modm-io/cmsis-svd-stm32/main"


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
    configure_preset: str | None
    build_preset: str | None


@dataclass
class SvdField:
    name: str
    bit_offset: int
    bit_width: int


@dataclass
class SvdRegister:
    name: str
    address_offset: int
    size: int
    fields: list[SvdField]


def _read_yaml(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        data = yaml.safe_load(handle) or {}
    if not isinstance(data, dict):
        raise typer.BadParameter(f"Config file must contain a mapping: {path}")
    return data


def _load_config(config: Path | None) -> ProjectConfig:
    if config is None:
        return ProjectConfig(
            None, None, None, None, None, None, None, None, None, None, None, [],
            None, [], None, [], None, None, None, None
        )

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
        configure_preset=data.get("configure_preset"),
        build_preset=data.get("build_preset"),
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
        configure_preset=(configure_preset or config.configure_preset),
        build_preset=(build_preset or config.build_preset),
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
    workspace_candidate = workspace / candidate
    if workspace_candidate.exists():
        return str(workspace_candidate)
    return cfg


def _openocd_quote(value: str) -> str:
    normalized = value.replace("\\", "/")
    return "{" + normalized + "}"


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


def _safe_echo(text: str, *, err: bool = False) -> None:
    stream = sys.stderr if err else sys.stdout
    encoding = getattr(stream, "encoding", None) or "utf-8"
    normalized = text.encode(encoding, errors="replace").decode(encoding, errors="replace")
    typer.echo(normalized, err=err)


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
        _safe_echo(completed.stdout.rstrip())
    if completed.returncode != 0:
        if completed.stderr:
            _safe_echo(completed.stderr.rstrip(), err=True)
        raise typer.Exit(completed.returncode)
    if completed.stderr:
        _safe_echo(completed.stderr.rstrip(), err=True)
    return completed


def _state_dir(workspace: Path) -> Path:
    return workspace / ".stm32-agent"


def _logs_dir(workspace: Path) -> Path:
    return _state_dir(workspace) / "logs"


def _session_file(workspace: Path) -> Path:
    return _state_dir(workspace) / "session.json"


def _project_profile_file(workspace: Path) -> Path:
    return _state_dir(workspace) / "project_profile.json"


def _session_state_file(workspace: Path) -> Path:
    return _state_dir(workspace) / "session_state.json"


def _observation_file(workspace: Path) -> Path:
    return _state_dir(workspace) / "observation.json"


def _verification_report_file(workspace: Path) -> Path:
    return _state_dir(workspace) / "verification_report.json"


def _svd_dir(workspace: Path) -> Path:
    return _state_dir(workspace) / "svd"


def _ensure_state_dirs(workspace: Path) -> None:
    _logs_dir(workspace).mkdir(parents=True, exist_ok=True)
    _svd_dir(workspace).mkdir(parents=True, exist_ok=True)


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")


def _read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def _write_session(workspace: Path, payload: dict[str, Any]) -> None:
    _ensure_state_dirs(workspace)
    _write_json(_session_file(workspace), payload)


def _read_session(workspace: Path) -> dict[str, Any]:
    session_path = _session_file(workspace)
    if not session_path.exists():
        raise typer.BadParameter(f"session file not found: {session_path}")
    return json.loads(session_path.read_text(encoding="utf-8"))


def _remove_session(workspace: Path) -> None:
    session_path = _session_file(workspace)
    if session_path.exists():
        session_path.unlink()


def _compact_path(path: str | None) -> str | None:
    if path is None:
        return None
    return path.replace("\\", "/")


def _update_project_profile(project: ProjectConfig, workspace: Path, *, backend: str | None = None) -> None:
    _ensure_state_dirs(workspace)
    current = _read_json(_project_profile_file(workspace))
    payload = {
        "project_name": project.project_name or current.get("project_name") or workspace.name,
        "workspace": _compact_path(str(workspace)),
        "elf": _compact_path(str(project.elf)) if project.elf else current.get("elf"),
        "build_dir": _compact_path(str(project.build_dir)) if project.build_dir else current.get("build_dir"),
        "chip": current.get("chip"),
        "probe": project.probe or current.get("probe"),
        "backend": backend or project.backend or current.get("backend") or "openocd",
        "rtos": current.get("rtos", "unknown"),
        "serial_port": project.serial_port or current.get("serial_port"),
        "baudrate": project.baudrate or current.get("baudrate"),
        "configure_preset": project.configure_preset or current.get("configure_preset"),
        "build_preset": project.build_preset or current.get("build_preset"),
        "svd": current.get("svd"),
        "generated_at": int(time.time()),
    }
    _write_json(_project_profile_file(workspace), payload)


def _github_get_json(url: str) -> Any:
    request = Request(
        url,
        headers={
            "Accept": "application/vnd.github+json",
            "User-Agent": "stm32-ai-agent/0.1.0",
        },
    )
    with urlopen(request, timeout=20) as response:
        return json.loads(response.read().decode("utf-8"))


def _github_download_text(url: str) -> str:
    request = Request(
        url,
        headers={"User-Agent": "stm32-ai-agent/0.1.0"},
    )
    with urlopen(request, timeout=30) as response:
        return response.read().decode("utf-8")


def _normalize_chip_model(chip: str) -> str:
    normalized = chip.strip().upper()
    if not normalized.startswith("STM32"):
        raise typer.BadParameter("chip must start with STM32, for example STM32H750VBT6")
    return normalized


def _infer_svd_family_dir(chip: str) -> str:
    normalized = _normalize_chip_model(chip)
    if normalized.startswith("STM32H7R") or normalized.startswith("STM32H7S"):
        return "stm32h7rs"
    if normalized.startswith("STM32WB0"):
        return "stm32wb0"
    if normalized.startswith("STM32WL3"):
        return "stm32wl3"
    if normalized.startswith("STM32WBA"):
        return "stm32wba5"
    if normalized.startswith("STM32L4R") or normalized.startswith("STM32L4S") or normalized.startswith("STM32L4P") or normalized.startswith("STM32L4Q"):
        return "stm32l4+"
    family = normalized[5:7].lower()
    supported = {
        "c0", "f0", "f1", "f2", "f3", "f4", "f7",
        "g0", "g4", "h5", "h7", "l0", "l1", "l4", "l5",
        "n6", "u0", "u3", "u5", "wb", "wl",
    }
    if family not in supported:
        raise typer.BadParameter(f"unsupported STM32 family for SVD auto-fetch: {chip}")
    return f"stm32{family}"


def _chip_search_tokens(chip: str) -> list[str]:
    normalized = _normalize_chip_model(chip)
    base = normalized[:9]
    family = normalized[:7]
    tokens = [normalized, base, family]
    series = normalized[:11]
    if len(series) > len(base):
        tokens.append(series)
    return list(dict.fromkeys(tokens))


def _pick_svd_candidate(chip: str, entries: list[dict[str, Any]]) -> dict[str, Any] | None:
    files = [entry for entry in entries if entry.get("type") == "file" and entry.get("name", "").lower().endswith(".svd")]
    if not files:
        return None
    tokens = _chip_search_tokens(chip)
    ranked: list[tuple[int, dict[str, Any]]] = []
    for entry in files:
        name_upper = entry["name"].upper()
        score = 0
        for index, token in enumerate(tokens):
            if token in name_upper:
                score = max(score, 100 - index * 10 + len(token))
        if score == 0 and tokens[1].endswith("X") is False:
            wildcard = tokens[1][:-1] + "X"
            if wildcard in name_upper:
                score = 70
        if score > 0:
            ranked.append((score, entry))
    if ranked:
        ranked.sort(key=lambda item: (-item[0], item[1]["name"]))
        return ranked[0][1]
    return None


def _record_svd_profile(
    workspace: Path,
    *,
    chip: str,
    family_dir: str,
    local_path: Path,
    source_url: str,
) -> None:
    current = _read_json(_project_profile_file(workspace))
    current.update(
        {
            "chip": chip,
            "svd": {
                "chip": chip,
                "family_dir": family_dir,
                "local_path": _compact_path(str(local_path)),
                "source_url": source_url,
                "fetched_at": int(time.time()),
            },
        }
    )
    _write_json(_project_profile_file(workspace), current)


def _svd_strip(tag: str) -> str:
    return tag.split("}", 1)[-1]


def _svd_child_text(node: ET.Element, name: str) -> str | None:
    for child in node:
        if _svd_strip(child.tag) == name:
            return child.text.strip() if child.text else None
    return None


def _svd_parse_int(value: str | None, default: int = 0) -> int:
    if value is None:
        return default
    raw = value.strip()
    if raw.lower().startswith("0x"):
        return int(raw, 16)
    if raw.lower().startswith("#"):
        return int(raw[1:], 2)
    return int(raw, 10)


def _resolve_svd_path(workspace: Path, svd_path: Path | None = None) -> Path:
    if svd_path is not None:
        return svd_path.resolve()
    profile = _read_json(_project_profile_file(workspace))
    svd_info = profile.get("svd") or {}
    local_path = svd_info.get("local_path")
    if not local_path:
        raise typer.BadParameter(
            f"SVD file not configured for {workspace}. Run `stm32-agent svd fetch --workspace \"{workspace}\" --chip <STM32...>` first."
        )
    path = Path(local_path)
    if not path.exists():
        raise typer.BadParameter(
            f"SVD file not found: {path}. Re-run `stm32-agent svd fetch` or provide --svd-path explicitly."
        )
    return path


def _load_svd_peripheral(svd_path: Path, peripheral_name: str) -> tuple[str, int, list[SvdRegister]]:
    tree = ET.parse(svd_path)
    root = tree.getroot()
    peripherals_node = next((child for child in root.iter() if _svd_strip(child.tag) == "peripherals"), None)
    if peripherals_node is None:
        raise typer.BadParameter(f"Invalid SVD file, missing peripherals: {svd_path}")

    target_name = peripheral_name.upper()
    peripheral_node = None
    for candidate in peripherals_node:
        if _svd_strip(candidate.tag) != "peripheral":
            continue
        name = _svd_child_text(candidate, "name")
        if name and name.upper() == target_name:
            peripheral_node = candidate
            break
    if peripheral_node is None:
        raise typer.BadParameter(f"Peripheral {peripheral_name} not found in SVD: {svd_path.name}")

    base_address = _svd_parse_int(_svd_child_text(peripheral_node, "baseAddress"))
    registers_node = next((child for child in peripheral_node if _svd_strip(child.tag) == "registers"), None)
    registers: list[SvdRegister] = []
    if registers_node is not None:
        for register_node in registers_node:
            if _svd_strip(register_node.tag) != "register":
                continue
            register_name = _svd_child_text(register_node, "name")
            if not register_name:
                continue
            fields_node = next((child for child in register_node if _svd_strip(child.tag) == "fields"), None)
            fields: list[SvdField] = []
            if fields_node is not None:
                for field_node in fields_node:
                    if _svd_strip(field_node.tag) != "field":
                        continue
                    field_name = _svd_child_text(field_node, "name")
                    if not field_name:
                        continue
                    bit_offset = _svd_child_text(field_node, "bitOffset")
                    bit_width = _svd_child_text(field_node, "bitWidth")
                    lsb = _svd_child_text(field_node, "lsb")
                    msb = _svd_child_text(field_node, "msb")
                    if bit_offset is not None and bit_width is not None:
                        offset = _svd_parse_int(bit_offset)
                        width = _svd_parse_int(bit_width)
                    elif lsb is not None and msb is not None:
                        offset = _svd_parse_int(lsb)
                        width = _svd_parse_int(msb) - offset + 1
                    else:
                        continue
                    fields.append(SvdField(name=field_name, bit_offset=offset, bit_width=width))
            registers.append(
                SvdRegister(
                    name=register_name,
                    address_offset=_svd_parse_int(_svd_child_text(register_node, "addressOffset")),
                    size=_svd_parse_int(_svd_child_text(register_node, "size"), default=32),
                    fields=fields,
                )
            )
    return target_name, base_address, registers


def _read_memory_word(
    project: ProjectConfig,
    workspace: Path,
    address: int,
    *,
    echo_output: bool = True,
) -> tuple[int, str]:
    completed = _session_gdb_command(
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


def _summarize_register_fields(register: SvdRegister, value: int) -> list[dict[str, Any]]:
    summary: list[dict[str, Any]] = []
    for field in register.fields:
        mask = (1 << field.bit_width) - 1
        field_value = (value >> field.bit_offset) & mask
        summary.append(
            {
                "name": field.name,
                "bit_offset": field.bit_offset,
                "bit_width": field.bit_width,
                "value": field_value,
                "value_hex": hex(field_value),
            }
        )
    return summary


@svd_app.command("fetch")
def svd_fetch(
    chip: str = typer.Option(..., help="STM32 chip model, for example STM32H750VBT6."),
    workspace: Path | None = typer.Option(None, help="STM32 project root. If omitted, use the current directory."),
    output: Path | None = typer.Option(None, help="Optional output path for the downloaded SVD."),
    force: bool = typer.Option(False, help="Overwrite existing local SVD file."),
) -> None:
    """Fetch an STM32 CMSIS-SVD file from modm-io/cmsis-svd-stm32."""
    resolved_workspace = (workspace or Path.cwd()).resolve()
    _ensure_state_dirs(resolved_workspace)
    normalized_chip = _normalize_chip_model(chip)
    family_dir = _infer_svd_family_dir(normalized_chip)
    try:
        entries = _github_get_json(f"{SVD_REPO_API}/{quote(family_dir)}")
    except HTTPError as exc:
        raise typer.BadParameter(
            f"failed to query SVD repository for {family_dir}: HTTP {exc.code}. Please check network access or download manually from https://github.com/modm-io/cmsis-svd-stm32"
        ) from exc
    except URLError as exc:
        raise typer.BadParameter(
            f"failed to query SVD repository: {exc.reason}. Please check network access or download manually from https://github.com/modm-io/cmsis-svd-stm32"
        ) from exc

    candidate = _pick_svd_candidate(normalized_chip, entries if isinstance(entries, list) else [])
    if candidate is None:
        raise typer.BadParameter(
            f"no matching SVD found for {normalized_chip} under {family_dir}. Please inspect https://github.com/modm-io/cmsis-svd-stm32/tree/main/{family_dir} and choose a file manually."
        )

    local_path = output.resolve() if output is not None else (_svd_dir(resolved_workspace) / candidate["name"])
    if local_path.exists() and not force:
        typer.echo(f"SVD already exists: {local_path}")
        _record_svd_profile(
            resolved_workspace,
            chip=normalized_chip,
            family_dir=family_dir,
            local_path=local_path,
            source_url=candidate.get("download_url") or f"{SVD_REPO_RAW}/{family_dir}/{candidate['name']}",
        )
        return

    source_url = candidate.get("download_url") or f"{SVD_REPO_RAW}/{family_dir}/{candidate['name']}"
    try:
        content = _github_download_text(source_url)
    except HTTPError as exc:
        raise typer.BadParameter(
            f"failed to download {candidate['name']}: HTTP {exc.code}. Please retry later or download manually from {source_url}"
        ) from exc
    except URLError as exc:
        raise typer.BadParameter(
            f"failed to download {candidate['name']}: {exc.reason}. Please retry later or download manually from {source_url}"
        ) from exc

    local_path.parent.mkdir(parents=True, exist_ok=True)
    local_path.write_text(content, encoding="utf-8")
    _record_svd_profile(
        resolved_workspace,
        chip=normalized_chip,
        family_dir=family_dir,
        local_path=local_path,
        source_url=source_url,
    )
    _append_verification(
        resolved_workspace,
        action="svd_fetch",
        ok=True,
        summary=f"Fetched SVD for {normalized_chip}: {candidate['name']}",
        verification_status="cli_verified",
        evidence={"source_url": source_url, "local_path": _compact_path(str(local_path))},
        state={"chip": normalized_chip, "family_dir": family_dir},
    )
    typer.echo(f"SVD fetched: {local_path}")


def _extract_source_location(text: str) -> dict[str, Any]:
    pattern = re.compile(r"^(?P<symbol>.+?)\s*\(.*?\)\s+at\s+(?P<file>.+?):(?P<line>\d+)$", re.MULTILINE)
    match = pattern.search(text)
    if not match:
        return {}
    return {
        "symbol": match.group("symbol").strip(),
        "file": _compact_path(match.group("file").strip()),
        "line": int(match.group("line")),
    }


def _extract_registers(text: str) -> dict[str, str]:
    registers: dict[str, str] = {}
    for line in text.splitlines():
        match = re.match(r"^(r\d+|sp|lr|pc|xpsr|fpscr|msp|psp|primask|basepri|faultmask|control)\s+(\S+)", line.strip())
        if match:
            registers[match.group(1)] = match.group(2)
    return registers


def _extract_backtrace_lines(text: str, limit: int = 5) -> list[str]:
    frames = [line.strip() for line in text.splitlines() if line.strip().startswith("#")]
    return frames[:limit]


def _trim_lines(text: str, limit: int = 20) -> list[str]:
    lines = [line for line in text.splitlines() if line.strip()]
    return lines[-limit:]


def _latest_verification_entry(workspace: Path) -> dict[str, Any]:
    payload = _read_json(_verification_report_file(workspace))
    latest = payload.get("latest")
    return latest if isinstance(latest, dict) else {}


def _compact_observation_event(event: dict[str, Any]) -> dict[str, Any]:
    compact: dict[str, Any] = {
        "kind": event.get("kind"),
    }
    for key in ("source", "summary", "peripheral", "svd_path", "mode", "resume_address", "port", "baudrate", "log_file"):
        value = event.get(key)
        if value is not None:
            compact[key] = value

    if event.get("registers_compact"):
        compact["registers_compact"] = event["registers_compact"]
    if event.get("line"):
        compact["line"] = event["line"]
    if event.get("raw_excerpt"):
        compact["raw_excerpt"] = event["raw_excerpt"][:6]
    if event.get("decoded"):
        compact["decoded"] = [
            {
                "name": item.get("name"),
                "address": item.get("address"),
                "value_hex": item.get("value_hex"),
                "fields": [
                    {
                        "name": field.get("name"),
                        "value_hex": field.get("value_hex"),
                    }
                    for field in item.get("fields", [])[:6]
                ],
            }
            for item in event["decoded"][:3]
        ]
    return compact


def _recent_observations(workspace: Path, limit: int = 4) -> list[dict[str, Any]]:
    payload = _load_observation(workspace)
    history = payload.get("history", [])
    if not isinstance(history, list):
        return []
    return [_compact_observation_event(item) for item in history[-limit:]]


def _parse_snapshot_watch(spec: str) -> tuple[str, str | None]:
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


def _read_peripheral_snapshot(
    project: ProjectConfig,
    workspace: Path,
    *,
    watch_specs: list[str],
    svd_path: Path | None = None,
    echo_output: bool = True,
) -> list[dict[str, Any]]:
    if not watch_specs:
        return []

    resolved_svd_path = _resolve_svd_path(workspace, svd_path)
    decoded: list[dict[str, Any]] = []
    for spec in watch_specs:
        peripheral, register_name = _parse_snapshot_watch(spec)
        peripheral_name, base_address, registers = _load_svd_peripheral(resolved_svd_path, peripheral)
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
            value, _ = _read_memory_word(project, workspace, address, echo_output=echo_output)
            fields = _summarize_register_fields(item, value)
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


def _collect_snapshot_payload(
    project: ProjectConfig,
    workspace: Path,
    *,
    watch_specs: list[str],
    backtrace_limit: int,
    observation_limit: int,
    svd_path: Path | None = None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "workspace": _compact_path(str(workspace)),
        "captured_at": int(time.time()),
        "session_active": False,
        "current_location": {},
        "registers_compact": {},
        "top_backtrace": [],
        "peripheral_summary": [],
        "recent_observations": _recent_observations(workspace, limit=observation_limit),
        "verification": _latest_verification_entry(workspace),
    }

    session_path = _session_file(workspace)
    if not session_path.exists():
        state = _read_json(_session_state_file(workspace))
        if state:
            payload["session_state"] = state
        return payload

    session = _read_session(workspace)
    completed = _session_gdb_command(
        project,
        ["monitor halt", "frame", "info registers sp lr pc control", "bt"],
        workspace=workspace,
        echo_output=False,
    )
    source = _extract_source_location(completed.stdout)
    registers = _extract_registers(completed.stdout)
    backtrace = _extract_backtrace_lines(completed.stdout, limit=backtrace_limit)
    peripheral_summary = _read_peripheral_snapshot(
        project,
        workspace,
        watch_specs=watch_specs,
        svd_path=svd_path,
        echo_output=False,
    )

    payload.update(
        {
            "session_active": True,
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


def _load_observation(workspace: Path) -> dict[str, Any]:
    payload = _read_json(_observation_file(workspace))
    if not payload:
        payload = {"history": []}
    payload.setdefault("history", [])
    return payload


def _append_observation(workspace: Path, event: dict[str, Any], *, limit: int = 12) -> None:
    _ensure_state_dirs(workspace)
    payload = _load_observation(workspace)
    history = payload.setdefault("history", [])
    history.append(event)
    payload["history"] = history[-limit:]
    payload["latest"] = event
    payload["updated_at"] = int(time.time())
    _write_json(_observation_file(workspace), payload)


def _append_verification(
    workspace: Path,
    *,
    action: str,
    ok: bool,
    summary: str,
    verification_status: str,
    evidence: dict[str, Any] | None = None,
    state: dict[str, Any] | None = None,
    limit: int = 20,
) -> None:
    _ensure_state_dirs(workspace)
    path = _verification_report_file(workspace)
    payload = _read_json(path) or {"entries": []}
    entries = payload.setdefault("entries", [])
    entries.append(
        {
            "timestamp": int(time.time()),
            "action": action,
            "ok": ok,
            "summary": summary,
            "verification_status": verification_status,
            "evidence": evidence or {},
            "state": state or {},
        }
    )
    payload["entries"] = entries[-limit:]
    payload["latest"] = payload["entries"][-1]
    _write_json(path, payload)


def _update_session_state(
    workspace: Path,
    *,
    session: dict[str, Any] | None = None,
    status: str,
    action: str,
    source: dict[str, Any] | None = None,
    registers: dict[str, str] | None = None,
    summary: str | None = None,
) -> None:
    _ensure_state_dirs(workspace)
    current = _read_json(_session_state_file(workspace))
    payload = {
        "session_id": current.get("session_id") or f"{workspace.name}-{int(time.time())}",
        "workspace": _compact_path(str(workspace)),
        "backend": (session or {}).get("backend", current.get("backend")),
        "status": status,
        "last_action": action,
        "updated_at": int(time.time()),
        "source": source or current.get("source"),
        "registers_compact": registers or current.get("registers_compact"),
        "summary": summary or current.get("summary"),
    }
    if session:
        payload["gdb_port"] = session.get("gdb_port")
        payload["server_kind"] = session.get("server_kind")
        payload["server_pid"] = session.get("server_pid")
    _write_json(_session_state_file(workspace), payload)


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


def _run_gdb_batch(
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
        _safe_echo(completed.stdout.rstrip())
    if completed.returncode != 0:
        if echo_output and completed.stderr:
            _safe_echo(completed.stderr.rstrip(), err=True)
        raise typer.Exit(completed.returncode)
    if echo_output and completed.stderr:
        _safe_echo(completed.stderr.rstrip(), err=True)
    return completed


def _resolve_session(project: ProjectConfig, workspace: Path | None = None) -> tuple[Path, dict[str, Any]]:
    resolved_workspace = _require_path(workspace or project.workspace, "workspace is required")
    return resolved_workspace, _read_session(resolved_workspace)


def _require_gdb() -> str:
    gdb = _resolve_executable("arm-none-eabi-gdb", "ARM_NONE_EABI_GDB")
    if not gdb:
        raise typer.BadParameter("arm-none-eabi-gdb was not found. Add it to PATH or set ARM_NONE_EABI_GDB.")
    return gdb


def _session_gdb_command(
    project: ProjectConfig,
    commands: list[str],
    *,
    workspace: Path | None = None,
    echo_output: bool = True,
) -> subprocess.CompletedProcess[str]:
    resolved_workspace, session = _resolve_session(project, workspace)
    return _run_gdb_batch(
        _require_gdb(),
        Path(session["elf"]),
        int(session["gdb_port"]),
        commands,
        cwd=resolved_workspace,
        echo_output=echo_output,
    )


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
    configure_preset: str | None = typer.Option(None, help="CMake configure preset name."),
    build_preset: str | None = typer.Option(None, help="CMake build preset name."),
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
        configure_preset=configure_preset,
        build_preset=build_preset,
    )
    resolved_workspace = _require_path(project.workspace, "workspace is required")
    resolved_build_dir = project.build_dir or (resolved_workspace / "build")
    cmake = _resolve_executable("cmake", "CMAKE")
    if not cmake:
        raise typer.BadParameter("cmake was not found. Add it to PATH or set CMAKE.")
    if not (resolved_workspace / "CMakeLists.txt").exists():
        raise typer.BadParameter(f"CMakeLists.txt not found under {resolved_workspace}")

    if project.configure_preset:
        _update_project_profile(project, resolved_workspace)
        if fresh and resolved_build_dir.exists() and not dry_run:
            shutil.rmtree(resolved_build_dir)
        if configure:
            configure_command = [cmake, "--preset", project.configure_preset]
            _run_command(configure_command, cwd=resolved_workspace, dry_run=dry_run)

        build_command = [cmake, "--build", "--preset", project.build_preset or project.configure_preset]
        if target != "all":
            build_command.extend(["--target", target])
        if jobs > 0:
            build_command.extend(["-j", str(jobs)])
        _run_command(build_command, cwd=resolved_workspace, dry_run=dry_run)
        if not dry_run:
            _append_verification(
                resolved_workspace,
                action="build",
                ok=True,
                summary="Build completed with CMake preset.",
                verification_status="cli_verified",
                state={"build_dir": _compact_path(str(resolved_build_dir))},
            )
        return

    _update_project_profile(project, resolved_workspace)
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
    if not dry_run:
        _append_verification(
            resolved_workspace,
            action="build",
            ok=True,
            summary="Build completed with direct CMake invocation.",
            verification_status="cli_verified",
            state={"build_dir": _compact_path(str(resolved_build_dir))},
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
    _update_project_profile(project, resolved_workspace, backend=_resolve_backend(project, backend))
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
            f"program {_openocd_quote(str(resolved_elf))} verify reset exit",
        ]
        _run_command(command, cwd=resolved_workspace, dry_run=dry_run)
        if not dry_run:
            _append_verification(
                resolved_workspace,
                action="flash",
                ok=True,
                summary="Flash completed with OpenOCD.",
                verification_status="hardware_verified",
                evidence={"elf": _compact_path(str(resolved_elf))},
                state={"backend": "openocd"},
            )
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
        if not dry_run:
            _append_verification(
                resolved_workspace,
                action="flash",
                ok=True,
                summary="Flash completed with ST-LINK backend.",
                verification_status="hardware_verified",
                evidence={"elf": _compact_path(str(resolved_elf))},
                state={"backend": "stlink"},
            )
        return

    raise typer.BadParameter(f"Unsupported backend: {resolved_backend}")


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
    project = _merge_config(_load_config(config), workspace=workspace)
    resolved_workspace = _require_path(project.workspace, "workspace is required")
    _update_project_profile(project, resolved_workspace)
    port = serial_port or project.serial_port
    if not port:
        raise typer.BadParameter("serial_port is required")
    resolved_baudrate = baudrate or project.baudrate
    if not resolved_baudrate:
        raise typer.BadParameter("baudrate is required")

    resolved_log_file = log_file
    if resolved_log_file is not None and not resolved_log_file.is_absolute():
        resolved_log_file = resolved_workspace / resolved_log_file
    if resolved_log_file is not None:
        resolved_log_file.parent.mkdir(parents=True, exist_ok=True)

    typer.echo(f"monitoring {port} @ {resolved_baudrate}")
    start_time = time.monotonic()
    handle = None
    try:
        if resolved_log_file is not None:
            handle = resolved_log_file.open("a", encoding="utf-8")

        with serial.Serial(port=port, baudrate=resolved_baudrate, timeout=0.2) as device:
            while True:
                if duration > 0 and (time.monotonic() - start_time) >= duration:
                    break

                chunk = device.readline()
                if not chunk:
                    continue

                text = chunk.decode("utf-8", errors="replace").rstrip("\r\n")
                rendered = text if raw else f"[{time.strftime('%H:%M:%S')}] {text}"
                typer.echo(rendered)
                if handle is not None:
                    handle.write(rendered + "\n")
                    handle.flush()
                _append_observation(
                    resolved_workspace,
                    {
                        "kind": "monitor",
                        "port": port,
                        "baudrate": resolved_baudrate,
                        "line": rendered,
                        "log_file": _compact_path(str(resolved_log_file)) if resolved_log_file else None,
                    },
                )
    except KeyboardInterrupt:
        typer.echo("monitor interrupted")
    except serial.SerialException as exc:
        raise typer.BadParameter(str(exc)) from exc
    finally:
        if handle is not None:
            handle.close()


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
    _update_project_profile(project, resolved_workspace, backend=resolved_backend)
    _update_session_state(
        resolved_workspace,
        session=payload,
        status="halted_or_waiting",
        action="debug_start",
        summary=f"Debug session started with {session_kind}.",
    )
    _append_verification(
        resolved_workspace,
        action="debug_start",
        ok=True,
        summary="Debug session started.",
        verification_status="hardware_verified",
        evidence={
            "session_path": _compact_path(str(_session_file(resolved_workspace))),
            "server_log": _compact_path(str(openocd_log)),
        },
        state={"backend": resolved_backend, "server_kind": session_kind},
    )
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
    _update_session_state(
        resolved_workspace,
        session=session,
        status="stopped",
        action="debug_stop",
        summary=f"Debug session stopped for pid={pid}.",
    )
    _append_verification(
        resolved_workspace,
        action="debug_stop",
        ok=True,
        summary="Debug session stopped.",
        verification_status="cli_verified",
        state={"server_pid": pid},
    )
    typer.echo(f"session stopped: pid={pid}")


@debug_app.command("step")
def debug_step(
    config: Path | None = typer.Option(None, "--config", "-c", help="Path to a YAML project config."),
    workspace: Path | None = typer.Option(None, help="STM32 project root."),
    instruction: bool = typer.Option(True, "--instruction/--source", help="Use stepi or step."),
) -> None:
    """Perform one debug step."""
    project = _merge_config(_load_config(config), workspace=workspace)
    step_command = "stepi" if instruction else "step"
    resolved_workspace, session = _resolve_session(project, workspace)
    completed = _session_gdb_command(project, ["monitor halt", step_command, "bt"], workspace=workspace)
    source = _extract_source_location(completed.stdout)
    _update_session_state(
        resolved_workspace,
        session=session,
        status="halted",
        action="debug_step",
        source=source,
        summary=f"Single step completed at {source.get('symbol', 'unknown location')}.",
    )
    _append_observation(
        resolved_workspace,
        {
            "kind": "debug_step",
            "mode": step_command,
            "source": source,
            "raw_excerpt": _trim_lines(completed.stdout),
        },
    )
    _append_verification(
        resolved_workspace,
        action="debug_step",
        ok=True,
        summary=f"Single step completed at {source.get('symbol', 'unknown location')}.",
        verification_status="hardware_verified",
        evidence={"session_path": _compact_path(str(_session_file(resolved_workspace)))},
        state={"source": source},
    )


@debug_app.command("continue")
def debug_continue(
    config: Path | None = typer.Option(None, "--config", "-c", help="Path to a YAML project config."),
    workspace: Path | None = typer.Option(None, help="STM32 project root."),
    address: str | None = typer.Option(None, help="Optional resume address, for example 0x08000100."),
) -> None:
    """Continue the current debug session."""
    project = _merge_config(_load_config(config), workspace=workspace)
    resolved_workspace, session = _resolve_session(project, workspace)
    commands: list[str] = []
    if address is not None:
        commands.append(f"set $pc = {address}")
    commands.extend(["continue&", "disconnect"])
    _session_gdb_command(project, commands, workspace=workspace)
    summary = "Target resumed asynchronously."
    _update_session_state(
        resolved_workspace,
        session=session,
        status="running",
        action="debug_continue",
        summary=summary,
    )
    _append_observation(
        resolved_workspace,
        {
            "kind": "debug_continue",
            "resume_address": address,
            "summary": summary,
        },
    )
    _append_verification(
        resolved_workspace,
        action="debug_continue",
        ok=True,
        summary=summary,
        verification_status="hardware_verified",
        state={"resume_address": address},
    )
    typer.echo("target resumed")


@debug_app.command("registers")
def debug_registers(
    config: Path | None = typer.Option(None, "--config", "-c", help="Path to a YAML project config."),
    workspace: Path | None = typer.Option(None, help="STM32 project root."),
) -> None:
    """Dump registers from the current debug session."""
    project = _merge_config(_load_config(config), workspace=workspace)
    resolved_workspace, session = _resolve_session(project, workspace)
    completed = _session_gdb_command(project, ["monitor halt", "info registers"], workspace=workspace)
    source = _extract_source_location(completed.stdout)
    registers = _extract_registers(completed.stdout)
    _update_session_state(
        resolved_workspace,
        session=session,
        status="halted",
        action="debug_registers",
        source=source,
        registers={key: value for key, value in registers.items() if key in {"sp", "lr", "pc", "control"}},
        summary=f"Registers captured at {source.get('symbol', 'unknown location')}.",
    )
    _append_observation(
        resolved_workspace,
        {
            "kind": "registers",
            "source": source,
            "registers_compact": {key: value for key, value in registers.items() if key in {"sp", "lr", "pc", "control"}},
            "raw_excerpt": _trim_lines(completed.stdout),
        },
    )
    _append_verification(
        resolved_workspace,
        action="debug_registers",
        ok=True,
        summary=f"Registers captured at {source.get('symbol', 'unknown location')}.",
        verification_status="hardware_verified",
        state={"source": source},
    )


@debug_app.command("backtrace")
def debug_backtrace(
    config: Path | None = typer.Option(None, "--config", "-c", help="Path to a YAML project config."),
    workspace: Path | None = typer.Option(None, help="STM32 project root."),
) -> None:
    """Dump the current backtrace."""
    project = _merge_config(_load_config(config), workspace=workspace)
    resolved_workspace, session = _resolve_session(project, workspace)
    completed = _session_gdb_command(project, ["monitor halt", "bt"], workspace=workspace)
    source = _extract_source_location(completed.stdout)
    _update_session_state(
        resolved_workspace,
        session=session,
        status="halted",
        action="debug_backtrace",
        source=source,
        summary=f"Backtrace captured at {source.get('symbol', 'unknown location')}.",
    )
    _append_observation(
        resolved_workspace,
        {
            "kind": "backtrace",
            "source": source,
            "raw_excerpt": _trim_lines(completed.stdout),
        },
    )
    _append_verification(
        resolved_workspace,
        action="debug_backtrace",
        ok=True,
        summary=f"Backtrace captured at {source.get('symbol', 'unknown location')}.",
        verification_status="hardware_verified",
        state={"source": source},
    )


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
    if len(watch) > 3:
        raise typer.BadParameter("At most 3 --watch targets are supported per snapshot.")

    project = _merge_config(_load_config(config), workspace=workspace)
    resolved_workspace = _require_path(project.workspace, "workspace is required")
    payload = _collect_snapshot_payload(
        project,
        resolved_workspace,
        watch_specs=watch,
        backtrace_limit=backtrace_limit,
        observation_limit=observation_limit,
        svd_path=svd_path,
    )

    if payload.get("session_active"):
        session = _read_session(resolved_workspace)
        source = payload.get("current_location") or {}
        registers = payload.get("registers_compact") or {}
        _update_session_state(
            resolved_workspace,
            session=session,
            status="halted",
            action="debug_snapshot",
            source=source if isinstance(source, dict) else None,
            registers=registers if isinstance(registers, dict) else None,
            summary=f"Snapshot captured at {source.get('symbol', 'unknown location')}.",
        )
        _append_observation(
            resolved_workspace,
            {
                "kind": "snapshot",
                "source": source,
                "registers_compact": registers,
                "summary": f"Snapshot captured with {len(payload.get('peripheral_summary', []))} peripheral summary item(s).",
                "raw_excerpt": payload.get("top_backtrace", []),
            },
        )
        _append_verification(
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
        payload["verification"] = _latest_verification_entry(resolved_workspace)

    typer.echo(json.dumps(payload, indent=2, ensure_ascii=False))


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
    project = _merge_config(_load_config(config), workspace=workspace)
    resolved_workspace, session = _resolve_session(project, workspace)
    resolved_svd_path = _resolve_svd_path(resolved_workspace, svd_path)
    peripheral_name, base_address, registers = _load_svd_peripheral(resolved_svd_path, peripheral)
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

    decoded: list[dict[str, Any]] = []
    for item in selected:
        address = base_address + item.address_offset
        value, raw_output = _read_memory_word(project, resolved_workspace, address)
        fields = _summarize_register_fields(item, value)
        decoded.append(
            {
                "name": item.name,
                "address": f"0x{address:08x}",
                "value": value,
                "value_hex": f"0x{value:08x}",
                "fields": fields,
                "raw_excerpt": _trim_lines(raw_output, limit=4),
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
    _update_session_state(
        resolved_workspace,
        session=session,
        status="halted",
        action="debug_peripheral_read",
        summary=summary,
    )
    _append_observation(
        resolved_workspace,
        {
            "kind": "peripheral_read",
            "peripheral": peripheral_name,
            "svd_path": _compact_path(str(resolved_svd_path)),
            "decoded": decoded,
        },
    )
    _append_verification(
        resolved_workspace,
        action="debug_peripheral_read",
        ok=True,
        summary=summary,
        verification_status="hardware_verified",
        evidence={"svd_path": _compact_path(str(resolved_svd_path))},
        state=compact,
    )


if __name__ == "__main__":
    app()
