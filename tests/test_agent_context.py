from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from stm32_agent.agent import context as app_context
from stm32_agent.infrastructure import project as project_ops
from stm32_agent.infrastructure import state as state_store


class AgentContextTests(unittest.TestCase):
    def test_build_agent_context_returns_structured_runtime_summary(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            workspace = Path(tmp_dir)
            state_store.ensure_state_dirs(workspace)

            session = {
                "session_id": "stm32-demo",
                "backend": "openocd",
                "gdb_port": 3333,
                "server_kind": "openocd",
                "server_pid": 4321,
            }
            state_store.write_session(workspace, session)
            state_store.update_project_profile(
                project_ops.ProjectConfig(
                    project_name="demo",
                    workspace=workspace,
                    elf=workspace / "demo.elf",
                ),
                workspace,
                backend="openocd",
            )
            state_store.update_session_state(
                workspace,
                session=session,
                status="halted",
                action="debug_snapshot",
                source={"symbol": "main", "line": 12},
                registers={"pc": "0x08000000"},
                summary="Snapshot captured at main.",
            )
            state_store.append_observation(
                workspace,
                {
                    "kind": "snapshot",
                    "summary": "Snapshot captured.",
                    "registers_compact": {"pc": "0x08000000"},
                },
            )
            state_store.append_verification(
                workspace,
                action="debug_snapshot",
                ok=True,
                summary="Snapshot captured at main.",
                verification_status="hardware_verified",
                evidence={"session": "stm32-demo"},
                state={"backend": "openocd"},
            )

            payload = app_context.build_agent_context(workspace)

            self.assertEqual(payload["runtime"]["session_status"], "halted")
            self.assertFalse(payload["runtime"]["session_busy"])
            self.assertEqual(payload["session_state"]["session_id"], "stm32-demo")
            self.assertEqual(payload["latest_verification"]["verification_status"], "hardware_verified")
            self.assertIn("debug continue", payload["recommended_actions"])


if __name__ == "__main__":
    unittest.main()
