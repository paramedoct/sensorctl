from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from sensors.config import AppConfig, ConfigError, load_config
from sensors.drivers.registry import DriverRegistry

VALID_CONFIG = """
version = 1

[database]
path = "/tmp/sensors.db"

[buses.mock_main]
type = "mock"

[[sensors]]
id = "counter"
driver = "mock"
bus = "mock_main"
interval_ms = 100
location = "test"

[sensors.options]
start = 2
step = 3
"""


class ConfigTest(unittest.TestCase):
    def load(self, contents: str) -> AppConfig:
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        path = Path(directory.name) / "sensors.toml"
        path.write_text(contents)
        return load_config(path)

    def test_loads_valid_configuration(self) -> None:
        config = self.load(VALID_CONFIG)
        DriverRegistry().validate(config)
        self.assertEqual(config.sensors[0].interval_ms, 100)
        self.assertEqual(config.sensors[0].options["step"], 3)

    def test_rejects_unknown_key(self) -> None:
        with self.assertRaisesRegex(ConfigError, "unknown sensor key"):
            self.load(
                VALID_CONFIG.replace('location = "test"', 'location = "test"\ntyop = 1')
            )

    def test_rejects_duplicate_sensor_id(self) -> None:
        duplicate = (
            VALID_CONFIG
            + """
[[sensors]]
id = "counter"
driver = "mock"
bus = "mock_main"
interval_ms = 100
location = "other"
"""
        )
        with self.assertRaisesRegex(ConfigError, "duplicate sensor id"):
            self.load(duplicate)

    def test_rejects_driver_bus_mismatch(self) -> None:
        invalid = VALID_CONFIG.replace(
            '[buses.mock_main]\ntype = "mock"',
            '[buses.mock_main]\ntype = "uart"\ndevice = "/dev/ttyS0"',
        )
        with self.assertRaisesRegex(ConfigError, "does not support"):
            DriverRegistry().validate(self.load(invalid))
