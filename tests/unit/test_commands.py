from __future__ import annotations

import contextlib
import io
import unittest
from pathlib import Path
from unittest.mock import patch

import commands


class CommandsTest(unittest.TestCase):
    def test_uses_sensorctl_default_paths(self) -> None:
        self.assertEqual(commands.DEFAULT_CONFIG, Path("/etc/sensorctl/sensorctl.toml"))
        self.assertEqual(commands.DEFAULT_STATUS, Path("/run/sensorctl/status.json"))

    def test_start_validates_before_service_change(self) -> None:
        config = Path("config.toml")
        with (
            patch("commands._validate", return_value=0) as validate,
            patch("commands.control.start", return_value=0) as start,
        ):
            result = commands.main(["start", "--config", str(config)])
        self.assertEqual(result, 0)
        validate.assert_called_once_with(config)
        start.assert_called_once_with()

    def test_validation_failure_prevents_service_change(self) -> None:
        with (
            patch("commands._validate", side_effect=RuntimeError("invalid")),
            patch("commands.control.restart") as restart,
            contextlib.redirect_stderr(io.StringIO()),
        ):
            result = commands.main(["restart"])
        self.assertEqual(result, 1)
        restart.assert_not_called()

    def test_status_combines_service_and_collector_status(self) -> None:
        with (
            patch("commands.control.show_status") as service_status,
            patch("commands._status", return_value=0) as collector_status,
        ):
            result = commands.main(["status"])
        self.assertEqual(result, 0)
        service_status.assert_called_once_with()
        collector_status.assert_called_once_with(
            commands.DEFAULT_CONFIG, commands.DEFAULT_STATUS
        )

    def test_failed_diagnosis_skips_journal(self) -> None:
        with (
            patch("commands._diagnose", return_value=1),
            patch("commands.control.show_journal") as journal,
        ):
            result = commands.main(["diagnose"])
        self.assertEqual(result, 1)
        journal.assert_not_called()
