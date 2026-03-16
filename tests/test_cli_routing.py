from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest import mock

from typer.testing import CliRunner

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from stm32_agent.interfaces import cli
from stm32_agent.interfaces.cli import app


class CliRoutingTests(unittest.TestCase):
    def setUp(self) -> None:
        self.runner = CliRunner()

    @mock.patch("stm32_agent.interfaces.cli.renderers.render_doctor")
    @mock.patch("stm32_agent.interfaces.cli.doctor_tools.run_doctor")
    @mock.patch("stm32_agent.interfaces.cli.project_app.load_project")
    def test_doctor_command_delegates_to_application(
        self,
        load_project: mock.Mock,
        run_doctor: mock.Mock,
        render_doctor: mock.Mock,
    ) -> None:
        load_project.return_value = mock.sentinel.project
        run_doctor.return_value = mock.Mock(ok=True)

        result = self.runner.invoke(app, ["doctor"])

        self.assertEqual(result.exit_code, 0)
        load_project.assert_called_once()
        run_doctor.assert_called_once_with(mock.sentinel.project)
        render_doctor.assert_called_once_with(run_doctor.return_value)

    @mock.patch("stm32_agent.interfaces.cli.renderers.render_svd_fetch")
    @mock.patch("stm32_agent.interfaces.cli.svd_tools.fetch_svd_file")
    def test_svd_fetch_delegates_to_application(
        self,
        fetch_svd_file: mock.Mock,
        render_svd_fetch: mock.Mock,
    ) -> None:
        fetch_svd_file.return_value = mock.sentinel.svd_result

        result = self.runner.invoke(app, ["svd", "fetch", "--chip", "STM32H750VBT6"])

        self.assertEqual(result.exit_code, 0)
        fetch_svd_file.assert_called_once()
        render_svd_fetch.assert_called_once_with(mock.sentinel.svd_result)

    @mock.patch("stm32_agent.interfaces.cli.renderers.render_build_result")
    @mock.patch("stm32_agent.interfaces.cli.build_tools.run_build")
    @mock.patch("stm32_agent.interfaces.cli.project_app.resolve_project")
    def test_build_command_delegates_to_application_and_renderer(
        self,
        resolve_project: mock.Mock,
        run_build: mock.Mock,
        render_build_result: mock.Mock,
    ) -> None:
        resolve_project.return_value = mock.sentinel.project
        run_build.return_value = mock.sentinel.build_result

        result = self.runner.invoke(app, ["build", "--dry-run"])

        self.assertEqual(result.exit_code, 0)
        resolve_project.assert_called_once()
        run_build.assert_called_once()
        render_build_result.assert_called_once_with(mock.sentinel.build_result)

    @mock.patch("stm32_agent.interfaces.cli.renderers.render_flash_result")
    @mock.patch("stm32_agent.interfaces.cli.flash_tools.run_flash")
    @mock.patch("stm32_agent.interfaces.cli.project_app.resolve_project")
    def test_flash_command_delegates_to_application_and_renderer(
        self,
        resolve_project: mock.Mock,
        run_flash: mock.Mock,
        render_flash_result: mock.Mock,
    ) -> None:
        resolve_project.return_value = mock.sentinel.project
        run_flash.return_value = mock.sentinel.flash_result

        result = self.runner.invoke(app, ["flash", "--dry-run"])

        self.assertEqual(result.exit_code, 0)
        resolve_project.assert_called_once()
        run_flash.assert_called_once()
        render_flash_result.assert_called_once_with(mock.sentinel.flash_result)

    @mock.patch("stm32_agent.interfaces.cli.renderers.render_monitor_result")
    @mock.patch("stm32_agent.interfaces.cli.monitor_tools.run_monitor")
    @mock.patch("stm32_agent.interfaces.cli.project_app.resolve_project")
    def test_monitor_command_passes_renderer_as_event_sink(
        self,
        resolve_project: mock.Mock,
        run_monitor: mock.Mock,
        render_monitor_result: mock.Mock,
    ) -> None:
        resolve_project.return_value = mock.sentinel.project
        run_monitor.return_value = mock.sentinel.monitor_result

        result = self.runner.invoke(app, ["monitor", "--duration", "0.1", "--serial-port", "COM6", "--baudrate", "115200"])

        self.assertEqual(result.exit_code, 0)
        resolve_project.assert_called_once()
        run_monitor.assert_called_once()
        self.assertIs(run_monitor.call_args.kwargs["on_event"], cli.renderers.render_monitor_event)
        render_monitor_result.assert_called_once_with(mock.sentinel.monitor_result)


if __name__ == "__main__":
    unittest.main()
