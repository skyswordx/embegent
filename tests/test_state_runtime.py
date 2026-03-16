from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from stm32_agent.infrastructure.state import runtime as state_runtime


class StateRuntimeTests(unittest.TestCase):
    def test_build_session_state_payload_uses_explicit_contract(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            workspace = Path(tmp_dir)
            payload = state_runtime.build_session_state_payload(
                workspace,
                {},
                session={
                    "session_id": "demo-session",
                    "backend": "openocd",
                    "gdb_port": 3333,
                    "server_kind": "openocd",
                    "server_pid": 1234,
                },
                status="halted",
                action="debug_snapshot",
                source={"symbol": "main", "line": 42},
                registers={"pc": "0x08000000"},
                summary="Snapshot captured.",
                lock_state={"busy": False, "status": "idle"},
            )

            self.assertEqual(payload["session_id"], "demo-session")
            self.assertEqual(payload["backend"], "openocd")
            self.assertEqual(payload["status"], "halted")
            self.assertEqual(payload["last_action"], "debug_snapshot")
            self.assertEqual(payload["source"]["symbol"], "main")
            self.assertEqual(payload["registers_compact"]["pc"], "0x08000000")
            self.assertEqual(payload["lock"]["status"], "idle")

    def test_append_verification_round_trips_latest_entry(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            workspace = Path(tmp_dir)
            state_runtime.append_verification(
                workspace,
                action="flash",
                ok=True,
                summary="Flash completed.",
                verification_status="hardware_verified",
                evidence={"elf": "demo.elf"},
                state={"backend": "openocd"},
            )

            latest = state_runtime.latest_verification_entry(workspace)

            self.assertEqual(latest["action"], "flash")
            self.assertTrue(latest["ok"])
            self.assertEqual(latest["verification_status"], "hardware_verified")
            self.assertEqual(latest["evidence"]["elf"], "demo.elf")


if __name__ == "__main__":
    unittest.main()
