from __future__ import annotations

from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any


def _compact_path(path: str | Path | None) -> str | None:
    if path is None:
        return None
    return str(path).replace("\\", "/")


@dataclass(slots=True)
class VerificationEntry:
    timestamp: int
    action: str
    ok: bool
    summary: str
    verification_status: str
    evidence: dict[str, Any] = field(default_factory=dict)
    state: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> VerificationEntry | None:
        if not isinstance(payload, dict) or not payload:
            return None
        return cls(
            timestamp=int(payload.get("timestamp", 0)),
            action=str(payload.get("action", "")),
            ok=bool(payload.get("ok", False)),
            summary=str(payload.get("summary", "")),
            verification_status=str(payload.get("verification_status", "")),
            evidence=dict(payload.get("evidence") or {}),
            state=dict(payload.get("state") or {}),
        )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class SessionState:
    session_id: str
    workspace: str
    backend: str | None = None
    status: str = "unknown"
    last_action: str | None = None
    updated_at: int = 0
    source: dict[str, Any] | None = None
    registers_compact: dict[str, str] | None = None
    summary: str | None = None
    lock: dict[str, Any] = field(default_factory=dict)
    gdb_port: int | None = None
    server_kind: str | None = None
    server_pid: int | None = None

    @classmethod
    def from_dict(cls, workspace: Path, payload: dict[str, Any]) -> SessionState:
        workspace_path = _compact_path(workspace.resolve()) or str(workspace.resolve())
        return cls(
            session_id=str(payload.get("session_id") or f"{workspace.name}-unknown"),
            workspace=str(payload.get("workspace") or workspace_path),
            backend=payload.get("backend"),
            status=str(payload.get("status") or "unknown"),
            last_action=payload.get("last_action"),
            updated_at=int(payload.get("updated_at", 0)),
            source=dict(payload.get("source")) if isinstance(payload.get("source"), dict) else None,
            registers_compact=(
                dict(payload.get("registers_compact"))
                if isinstance(payload.get("registers_compact"), dict)
                else None
            ),
            summary=payload.get("summary"),
            lock=dict(payload.get("lock") or {}),
            gdb_port=int(payload["gdb_port"]) if payload.get("gdb_port") is not None else None,
            server_kind=payload.get("server_kind"),
            server_pid=int(payload["server_pid"]) if payload.get("server_pid") is not None else None,
        )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class AgentRuntimeSummary:
    session_active: bool
    session_status: str
    session_busy: bool
    busy_action: str | None
    backend: str | None
    last_action: str | None
    last_verification_status: str | None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class AgentContext:
    workspace: str
    state_files: dict[str, str]
    capabilities: dict[str, bool]
    runtime: AgentRuntimeSummary
    recommended_actions: list[str]
    project_profile: dict[str, Any]
    session_state: SessionState
    recent_observations: list[dict[str, Any]]
    latest_verification: VerificationEntry | None = None

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["runtime"] = self.runtime.to_dict()
        payload["session_state"] = self.session_state.to_dict()
        payload["latest_verification"] = (
            self.latest_verification.to_dict() if self.latest_verification is not None else {}
        )
        return payload


@dataclass(slots=True)
class DoctorCheck:
    name: str
    result: str
    required: bool = False


@dataclass(slots=True)
class DoctorResult:
    backend: str
    checks: list[DoctorCheck]
    ok: bool
    required_keys: list[str] = field(default_factory=list)


@dataclass(slots=True)
class SvdFetchResult:
    chip: str
    family_dir: str
    candidate_name: str
    local_path: str
    source_url: str
    reused: bool


@dataclass(slots=True)
class CommandRunResult:
    command: list[str]
    cwd: str | None = None
    stdout: str = ""
    stderr: str = ""
    returncode: int | None = None
    dry_run: bool = False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class BuildResult:
    summary: str
    build_dir: str
    mode: str
    configured: bool
    dry_run: bool
    steps: list[CommandRunResult] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class FlashResult:
    summary: str
    backend: str
    elf: str
    dry_run: bool
    command_result: CommandRunResult

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class DebugCommandResult:
    summary: str
    ok: bool = True
    command: list[str] = field(default_factory=list)
    session_path: str | None = None
    pid: int | None = None
    backend: str | None = None
    payload: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class RegisterFieldSummary:
    name: str
    bit_offset: int
    bit_width: int
    value: int
    value_hex: str

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> RegisterFieldSummary:
        return cls(
            name=str(payload.get("name", "")),
            bit_offset=int(payload.get("bit_offset", 0)),
            bit_width=int(payload.get("bit_width", 0)),
            value=int(payload.get("value", 0)),
            value_hex=str(payload.get("value_hex", "0x0")),
        )


@dataclass(slots=True)
class PeripheralRegisterSummary:
    peripheral: str
    register: str
    address: str
    value: int
    value_hex: str
    fields: list[RegisterFieldSummary] = field(default_factory=list)

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> PeripheralRegisterSummary:
        return cls(
            peripheral=str(payload.get("peripheral", "")),
            register=str(payload.get("register", "")),
            address=str(payload.get("address", "")),
            value=int(payload.get("value", 0)),
            value_hex=str(payload.get("value_hex", "0x0")),
            fields=[
                RegisterFieldSummary.from_dict(item)
                for item in payload.get("fields", [])
                if isinstance(item, dict)
            ],
        )


@dataclass(slots=True)
class MonitorEvent:
    kind: str
    text: str
    port: str
    baudrate: int
    timestamp: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class MonitorResult:
    summary: str
    port: str
    baudrate: int
    duration: float
    raw: bool
    interrupted: bool
    line_count: int
    log_file: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class PeripheralReadResult:
    summary: str
    peripheral: str
    svd_path: str
    decoded: list[PeripheralRegisterSummary] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class ExecutionSnapshot:
    workspace: str
    captured_at: int
    session_active: bool
    current_location: dict[str, Any] = field(default_factory=dict)
    registers_compact: dict[str, str] = field(default_factory=dict)
    top_backtrace: list[str] = field(default_factory=list)
    peripheral_summary: list[PeripheralRegisterSummary] = field(default_factory=list)
    session_state: dict[str, Any] = field(default_factory=dict)
    recent_observations: list[dict[str, Any]] = field(default_factory=list)
    verification: dict[str, Any] = field(default_factory=dict)
    session: dict[str, Any] = field(default_factory=dict)
    agent_context: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> ExecutionSnapshot:
        return cls(
            workspace=str(payload.get("workspace", "")),
            captured_at=int(payload.get("captured_at", 0)),
            session_active=bool(payload.get("session_active", False)),
            current_location=dict(payload.get("current_location") or {}),
            registers_compact=dict(payload.get("registers_compact") or {}),
            top_backtrace=list(payload.get("top_backtrace") or []),
            peripheral_summary=[
                PeripheralRegisterSummary.from_dict(item)
                for item in payload.get("peripheral_summary", [])
                if isinstance(item, dict)
            ],
            session_state=dict(payload.get("session_state") or {}),
            recent_observations=list(payload.get("recent_observations") or []),
            verification=dict(payload.get("verification") or {}),
            session=dict(payload.get("session") or {}),
            agent_context=dict(payload.get("agent_context") or {}),
        )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
