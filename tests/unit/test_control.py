from __future__ import annotations

import subprocess
import unittest
from unittest.mock import patch

from sensors import control


class ControlTest(unittest.TestCase):
    @patch("sensors.control.os.geteuid", return_value=0)
    def test_enable_starts_service(self, _geteuid: object) -> None:
        completed = subprocess.CompletedProcess[object]([], 0)
        with patch("sensors.control.subprocess.run", return_value=completed) as runner:
            self.assertEqual(control.enable(), 0)
        runner.assert_called_once_with(
            ["systemctl", "enable", "--now", "sensors.service"], check=False
        )

    @patch("sensors.control.os.geteuid", return_value=1000)
    def test_start_requires_root(self, _geteuid: object) -> None:
        with self.assertRaisesRegex(PermissionError, "must run as root"):
            control.start()

    def test_status_does_not_require_root(self) -> None:
        completed = subprocess.CompletedProcess[object]([], 3)
        with patch("sensors.control.subprocess.run", return_value=completed) as runner:
            control.show_status()
        runner.assert_called_once_with(
            [
                "systemctl",
                "--no-pager",
                "--full",
                "status",
                "sensors.service",
            ],
            check=False,
        )

    @patch("sensors.control.shutil.which", return_value=None)
    def test_journal_is_optional(self, _which: object) -> None:
        with patch("sensors.control.subprocess.run") as runner:
            control.show_journal()
        runner.assert_not_called()
