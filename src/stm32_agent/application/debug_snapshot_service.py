from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

import typer

from ..agent import context as app_context
from ..infrastructure import debug_support as debug_ops
from ..infrastructure import project as project_ops
from ..infrastructure import state as state_store
from ..infrastructure import svd as svd_ops
from .debug_actions_service import locked_session
from . import verification_service as verify_tools


def emit_snapshot(
    project: project_ops.ProjectConfig,
    *,
    watch: list[str],
    svd_path: Path | None = None,
    backtrace_limit: int = 5,
    observation_limit: int = 4,
) -> None:
    if len(watch) > 3:
        raise typer.BadParameter("At most 3 --watch targets are supported per snapshot.")

    resolved_workspace = project_ops.require_path(project.workspace, "workspace is required")
    payload: dict[str, Any]
    with state_store.session_command_lock(resolved_workspace, action="debug_snapshot"):
        agent_context = app_context.build_agent_context(resolved_workspace, observation_limit=observation_limit)
        payload = debug_ops.collect_snapshot_payload(
            project,
            resolved_workspace,
            watch_specs=watch,
            backtrace_limit=backtrace_limit,
            observation_limit=observation_limit,
            svd_path=svd_path,
            agent_context=agent_context,
        )

        if payload.get("session_active"):
            session = state_store.read_session(resolved_workspace)
            source = payload.get("current_location") or {}
            registers = payload.get("registers_compact") or {}
            verify_tools.record_session_transition(
                resolved_workspace,
                session=session,
                action="debug_snapshot",
                status="halted",
                summary=f"Snapshot captured at {source.get('symbol', 'unknown location')}.",
                verification_status="hardware_verified",
                source=source if isinstance(source, dict) else None,
                registers=registers if isinstance(registers, dict) else None,
                observation={
                    "kind": "snapshot",
                    "source": source,
                    "registers_compact": registers,
                    "summary": f"Snapshot captured with {len(payload.get('peripheral_summary', []))} peripheral summary item(s).",
                    "raw_excerpt": payload.get("top_backtrace", []),
                },
                state={
                    "source": source,
                    "watch_count": len(watch),
                    "observation_count": len(payload.get("recent_observations", [])),
                },
            )
            payload["captured_at"] = int(time.time())

    refreshed_context = app_context.build_agent_context(
        resolved_workspace,
        observation_limit=observation_limit,
    )
    payload["session_state"] = refreshed_context["session_state"]
    payload["recent_observations"] = refreshed_context["recent_observations"]
    payload["verification"] = refreshed_context["latest_verification"]
    payload["agent_context"] = {
        "runtime": refreshed_context["runtime"],
        "recommended_actions": refreshed_context["recommended_actions"],
        "state_files": refreshed_context["state_files"],
    }

    typer.echo(json.dumps(payload, indent=2, ensure_ascii=False))


def read_peripheral(
    project: project_ops.ProjectConfig,
    *,
    peripheral: str,
    register: str | None = None,
    svd_path: Path | None = None,
    limit: int = 8,
) -> None:
    with locked_session(project, action="debug_peripheral_read") as (resolved_workspace, session):
        resolved_svd_path = svd_ops.resolve_svd_path(resolved_workspace, svd_path)
        peripheral_name, base_address, registers = svd_ops.load_svd_peripheral(resolved_svd_path, peripheral)
        selected = _select_registers(registers, peripheral_name, resolved_svd_path, register, limit)

        decoded: list[dict[str, Any]] = []
        for item in selected:
            address = base_address + item.address_offset
            value, raw_output = debug_ops.read_memory_word(project, resolved_workspace, address)
            fields = svd_ops.summarize_register_fields(item, value)
            decoded.append(
                {
                    "name": item.name,
                    "address": f"0x{address:08x}",
                    "value": value,
                    "value_hex": f"0x{value:08x}",
                    "fields": fields,
                    "raw_excerpt": debug_ops.trim_lines(raw_output, limit=4),
                }
            )

        summary = f"Decoded {len(decoded)} register(s) for {peripheral_name} using {resolved_svd_path.name}."
        _echo_decoded_registers(summary, decoded)
        compact = {
            "peripheral": peripheral_name,
            "registers": [
                {"name": item["name"], "address": item["address"], "value_hex": item["value_hex"]}
                for item in decoded
            ],
        }
        verify_tools.record_session_transition(
            resolved_workspace,
            session=session,
            action="debug_peripheral_read",
            status="halted",
            summary=summary,
            verification_status="hardware_verified",
            observation={
                "kind": "peripheral_read",
                "peripheral": peripheral_name,
                "svd_path": state_store.compact_path(str(resolved_svd_path)),
                "decoded": decoded,
            },
            evidence={"svd_path": state_store.compact_path(str(resolved_svd_path))},
            state=compact,
        )


def _select_registers(
    registers: list[Any],
    peripheral_name: str,
    resolved_svd_path: Path,
    register: str | None,
    limit: int,
) -> list[Any]:
    if register is None:
        return registers[:limit]

    target = register.upper()
    selected = [item for item in registers if item.name.upper() == target]
    if not selected:
        raise typer.BadParameter(
            f"Register {register} not found under peripheral {peripheral_name} in {resolved_svd_path.name}"
        )
    return selected


def _echo_decoded_registers(summary: str, decoded: list[dict[str, Any]]) -> None:
    typer.echo(summary)
    for item in decoded:
        typer.echo(f"{item['name']} @ {item['address']} = {item['value_hex']}")
        for field in item["fields"][:8]:
            typer.echo(
                f"  {field['name']}[{field['bit_offset']}:{field['bit_offset'] + field['bit_width'] - 1}] = {field['value_hex']}"
            )
        if len(item["fields"]) > 8:
            typer.echo(f"  ... {len(item['fields']) - 8} more fields")
