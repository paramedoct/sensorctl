from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from config import AppConfig, ConfigError, SensorConfig, load_config
from drivers.mock import MockDriver
from drivers.registry import DriverRegistry

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
        path = Path(directory.name) / "toml"
        path.write_text(contents)
        return load_config(path)

    def test_loads_valid_configuration(self) -> None:
        config = self.load(VALID_CONFIG)
        DriverRegistry().prepare(config)
        self.assertEqual(config.sensors[0].interval_ms, 100)
        self.assertEqual(config.sensors[0].options["step"], 3)
        self.assertEqual(config.buses["mock_main"].retries, 0)

    def test_loads_bmp280_example(self) -> None:
        path = Path(__file__).parents[2] / "config" / "bmp280.example.toml"
        config = load_config(path)
        prepared = DriverRegistry().prepare(config)
        driver = prepared.by_sensor_id["room_environment"]
        self.assertEqual(driver.fields[0].name, "temperature")

    def test_loads_typed_bus_values(self) -> None:
        config = self.load(
            VALID_CONFIG.replace(
                '[buses.mock_main]\ntype = "mock"',
                '[buses.mock_main]\ntype = "uart"\n'
                'device = "/dev/ttyS0"\nbaud_rate = 115200\nretries = 4',
            ).replace('driver = "mock"', 'driver = "unknown"')
        )
        bus = config.buses["mock_main"]
        self.assertEqual(bus.device, Path("/dev/ttyS0"))
        self.assertEqual(bus.baud_rate, 115200)
        self.assertEqual(bus.retries, 4)

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
            DriverRegistry().prepare(self.load(invalid))

    def test_rejects_shutdown_timeout_above_service_limit(self) -> None:
        invalid = VALID_CONFIG.replace(
            "version = 1", "version = 1\n\n[collector]\nshutdown_timeout_s = 11"
        )
        with self.assertRaisesRegex(ConfigError, "between 1 and 10"):
            self.load(invalid)

    def test_prepares_each_driver_once(self) -> None:
        created = 0

        class CountingDriver(MockDriver):
            def __init__(self, sensor: SensorConfig) -> None:
                nonlocal created
                created += 1
                super().__init__(sensor)

        config = self.load(VALID_CONFIG)
        prepared = DriverRegistry({"mock": CountingDriver}).prepare(config)
        self.assertEqual(created, 1)
        self.assertEqual(prepared.sensors, config.sensors)
        self.assertIsInstance(prepared.by_sensor_id["counter"], CountingDriver)
