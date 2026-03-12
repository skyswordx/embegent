from __future__ import annotations

import json
import time
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import Request, urlopen

import typer

from . import state as state_store

SVD_REPO_API = "https://api.github.com/repos/modm-io/cmsis-svd-stm32/contents"
SVD_REPO_RAW = "https://raw.githubusercontent.com/modm-io/cmsis-svd-stm32/main"


@dataclass(slots=True)
class SvdField:
    name: str
    bit_offset: int
    bit_width: int


@dataclass(slots=True)
class SvdRegister:
    name: str
    address_offset: int
    size: int
    fields: list[SvdField]


def github_get_json(url: str) -> Any:
    request = Request(
        url,
        headers={
            "Accept": "application/vnd.github+json",
            "User-Agent": "stm32-ai-agent/0.1.0",
        },
    )
    with urlopen(request, timeout=20) as response:
        return json.loads(response.read().decode("utf-8"))


def github_download_text(url: str) -> str:
    request = Request(url, headers={"User-Agent": "stm32-ai-agent/0.1.0"})
    with urlopen(request, timeout=30) as response:
        return response.read().decode("utf-8")


def normalize_chip_model(chip: str) -> str:
    normalized = chip.strip().upper()
    if not normalized.startswith("STM32"):
        raise typer.BadParameter("chip must start with STM32, for example STM32H750VBT6")
    return normalized


def infer_svd_family_dir(chip: str) -> str:
    normalized = normalize_chip_model(chip)
    if normalized.startswith("STM32H7R") or normalized.startswith("STM32H7S"):
        return "stm32h7rs"
    if normalized.startswith("STM32WB0"):
        return "stm32wb0"
    if normalized.startswith("STM32WL3"):
        return "stm32wl3"
    if normalized.startswith("STM32WBA"):
        return "stm32wba5"
    if (
        normalized.startswith("STM32L4R")
        or normalized.startswith("STM32L4S")
        or normalized.startswith("STM32L4P")
        or normalized.startswith("STM32L4Q")
    ):
        return "stm32l4+"
    family = normalized[5:7].lower()
    supported = {
        "c0",
        "f0",
        "f1",
        "f2",
        "f3",
        "f4",
        "f7",
        "g0",
        "g4",
        "h5",
        "h7",
        "l0",
        "l1",
        "l4",
        "l5",
        "n6",
        "u0",
        "u3",
        "u5",
        "wb",
        "wl",
    }
    if family not in supported:
        raise typer.BadParameter(f"unsupported STM32 family for SVD auto-fetch: {chip}")
    return f"stm32{family}"


def chip_search_tokens(chip: str) -> list[str]:
    normalized = normalize_chip_model(chip)
    base = normalized[:9]
    family = normalized[:7]
    tokens = [normalized, base, family]
    series = normalized[:11]
    if len(series) > len(base):
        tokens.append(series)
    return list(dict.fromkeys(tokens))


def pick_svd_candidate(chip: str, entries: list[dict[str, Any]]) -> dict[str, Any] | None:
    files = [
        entry
        for entry in entries
        if entry.get("type") == "file" and entry.get("name", "").lower().endswith(".svd")
    ]
    if not files:
        return None
    tokens = chip_search_tokens(chip)
    ranked: list[tuple[int, dict[str, Any]]] = []
    for entry in files:
        name_upper = entry["name"].upper()
        score = 0
        for index, token in enumerate(tokens):
            if token in name_upper:
                score = max(score, 100 - index * 10 + len(token))
        if score == 0 and not tokens[1].endswith("X"):
            wildcard = tokens[1][:-1] + "X"
            if wildcard in name_upper:
                score = 70
        if score > 0:
            ranked.append((score, entry))
    if not ranked:
        return None
    ranked.sort(key=lambda item: (-item[0], item[1]["name"]))
    return ranked[0][1]


def record_svd_profile(
    workspace: Path,
    *,
    chip: str,
    family_dir: str,
    local_path: Path,
    source_url: str,
) -> None:
    current = state_store.read_json(state_store.project_profile_file(workspace))
    current.update(
        {
            "chip": chip,
            "svd": {
                "chip": chip,
                "family_dir": family_dir,
                "local_path": state_store.compact_path(str(local_path)),
                "source_url": source_url,
                "fetched_at": int(time.time()),
            },
        }
    )
    state_store.write_json(state_store.project_profile_file(workspace), current)


def svd_strip(tag: str) -> str:
    return tag.split("}", 1)[-1]


def svd_child_text(node: ET.Element, name: str) -> str | None:
    for child in node:
        if svd_strip(child.tag) == name:
            return child.text.strip() if child.text else None
    return None


def svd_parse_int(value: str | None, default: int = 0) -> int:
    if value is None:
        return default
    raw = value.strip()
    if raw.lower().startswith("0x"):
        return int(raw, 16)
    if raw.lower().startswith("#"):
        return int(raw[1:], 2)
    return int(raw, 10)


def resolve_svd_path(workspace: Path, svd_path: Path | None = None) -> Path:
    if svd_path is not None:
        return svd_path.resolve()
    profile = state_store.read_json(state_store.project_profile_file(workspace))
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


def load_svd_peripheral(svd_path: Path, peripheral_name: str) -> tuple[str, int, list[SvdRegister]]:
    tree = ET.parse(svd_path)
    root = tree.getroot()
    peripherals_node = next((child for child in root.iter() if svd_strip(child.tag) == "peripherals"), None)
    if peripherals_node is None:
        raise typer.BadParameter(f"Invalid SVD file, missing peripherals: {svd_path}")

    target_name = peripheral_name.upper()
    peripheral_node = None
    for candidate in peripherals_node:
        if svd_strip(candidate.tag) != "peripheral":
            continue
        name = svd_child_text(candidate, "name")
        if name and name.upper() == target_name:
            peripheral_node = candidate
            break
    if peripheral_node is None:
        raise typer.BadParameter(f"Peripheral {peripheral_name} not found in SVD: {svd_path.name}")

    base_address = svd_parse_int(svd_child_text(peripheral_node, "baseAddress"))
    registers_node = next((child for child in peripheral_node if svd_strip(child.tag) == "registers"), None)
    registers: list[SvdRegister] = []
    if registers_node is not None:
        for register_node in registers_node:
            if svd_strip(register_node.tag) != "register":
                continue
            register_name = svd_child_text(register_node, "name")
            if not register_name:
                continue
            fields_node = next((child for child in register_node if svd_strip(child.tag) == "fields"), None)
            fields: list[SvdField] = []
            if fields_node is not None:
                for field_node in fields_node:
                    if svd_strip(field_node.tag) != "field":
                        continue
                    field_name = svd_child_text(field_node, "name")
                    if not field_name:
                        continue
                    bit_offset = svd_child_text(field_node, "bitOffset")
                    bit_width = svd_child_text(field_node, "bitWidth")
                    lsb = svd_child_text(field_node, "lsb")
                    msb = svd_child_text(field_node, "msb")
                    if bit_offset is not None and bit_width is not None:
                        offset = svd_parse_int(bit_offset)
                        width = svd_parse_int(bit_width)
                    elif lsb is not None and msb is not None:
                        offset = svd_parse_int(lsb)
                        width = svd_parse_int(msb) - offset + 1
                    else:
                        continue
                    fields.append(SvdField(name=field_name, bit_offset=offset, bit_width=width))
            registers.append(
                SvdRegister(
                    name=register_name,
                    address_offset=svd_parse_int(svd_child_text(register_node, "addressOffset")),
                    size=svd_parse_int(svd_child_text(register_node, "size"), default=32),
                    fields=fields,
                )
            )
    return target_name, base_address, registers


def summarize_register_fields(register: SvdRegister, value: int) -> list[dict[str, Any]]:
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


def fetch_svd(
    *,
    chip: str,
    workspace: Path,
    output: Path | None = None,
    force: bool = False,
) -> dict[str, Any]:
    resolved_workspace = workspace.resolve()
    state_store.ensure_state_dirs(resolved_workspace)
    normalized_chip = normalize_chip_model(chip)
    family_dir = infer_svd_family_dir(normalized_chip)
    try:
        entries = github_get_json(f"{SVD_REPO_API}/{quote(family_dir)}")
    except HTTPError as exc:
        raise typer.BadParameter(
            f"failed to query SVD repository for {family_dir}: HTTP {exc.code}. Please check network access or download manually from https://github.com/modm-io/cmsis-svd-stm32"
        ) from exc
    except URLError as exc:
        raise typer.BadParameter(
            f"failed to query SVD repository: {exc.reason}. Please check network access or download manually from https://github.com/modm-io/cmsis-svd-stm32"
        ) from exc

    candidate = pick_svd_candidate(normalized_chip, entries if isinstance(entries, list) else [])
    if candidate is None:
        raise typer.BadParameter(
            f"no matching SVD found for {normalized_chip} under {family_dir}. Please inspect https://github.com/modm-io/cmsis-svd-stm32/tree/main/{family_dir} and choose a file manually."
        )

    local_path = output.resolve() if output is not None else (state_store.svd_dir(resolved_workspace) / candidate["name"])
    source_url = candidate.get("download_url") or f"{SVD_REPO_RAW}/{family_dir}/{candidate['name']}"
    reused = local_path.exists() and not force
    if reused:
        record_svd_profile(
            resolved_workspace,
            chip=normalized_chip,
            family_dir=family_dir,
            local_path=local_path,
            source_url=source_url,
        )
        return {
            "chip": normalized_chip,
            "family_dir": family_dir,
            "candidate_name": candidate["name"],
            "local_path": local_path,
            "source_url": source_url,
            "reused": True,
        }

    try:
        content = github_download_text(source_url)
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
    record_svd_profile(
        resolved_workspace,
        chip=normalized_chip,
        family_dir=family_dir,
        local_path=local_path,
        source_url=source_url,
    )
    return {
        "chip": normalized_chip,
        "family_dir": family_dir,
        "candidate_name": candidate["name"],
        "local_path": local_path,
        "source_url": source_url,
        "reused": False,
    }
