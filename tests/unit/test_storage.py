from __future__ import annotations

import sqlite3
import tempfile
import unittest
from pathlib import Path

from sensors.config import (
    AppConfig,
    BusConfig,
    CollectorConfig,
    DatabaseConfig,
    SensorConfig,
)
from sensors.drivers.registry import DriverRegistry
from sensors.model import Sample
from sensors.storage.database import Database, _fingerprint


def make_config(path: Path, location: str = "test") -> AppConfig:
    return AppConfig(
        1,
        CollectorConfig(),
        DatabaseConfig(path),
        {"mock": BusConfig("mock", "mock")},
        (SensorConfig("counter", "mock", "mock", 100, location, True),),
    )


class DatabaseTest(unittest.TestCase):
    def setUp(self) -> None:
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.path = Path(self.directory.name) / "sensors.db"

    def test_writes_grouped_sample(self) -> None:
        config = make_config(self.path)
        database = Database(self.path)
        database.open()
        stored = database.register_sensors(
            config, DriverRegistry().prepare(config).by_sensor_id
        )
        database.write_samples(
            [Sample("counter", 10, 20, "boot", {"value": 4.0})], stored
        )
        database.close()
        connection = sqlite3.connect(self.path)
        row = connection.execute(
            """
            SELECT sample.wall_time_ns, measurement.value
            FROM sample JOIN measurement ON measurement.sample_id = sample.id
            """
        ).fetchone()
        connection.close()
        self.assertEqual(row, (10, 4.0))

    def test_configuration_change_creates_revision(self) -> None:
        database = Database(self.path)
        database.open()
        first = make_config(self.path)
        second = make_config(self.path, "other")
        database.register_sensors(first, DriverRegistry().prepare(first).by_sensor_id)
        database.register_sensors(second, DriverRegistry().prepare(second).by_sensor_id)
        database.close()
        connection = sqlite3.connect(self.path)
        count = connection.execute("SELECT COUNT(*) FROM sensor_instance").fetchone()
        connection.close()
        self.assertEqual(count, (2,))

    def test_fingerprint_remains_compatible_with_untyped_bus_values(self) -> None:
        sensor = SensorConfig(
            "example_counter",
            "mock",
            "mock_main",
            1000,
            "development",
            True,
            options={"start": 0.0, "step": 1.0},
        )
        self.assertEqual(
            _fingerprint(sensor, BusConfig("mock_main", "mock")),
            "714c6d1f58a64598b5646064428057ce43e688b879ed2ac59ab8fbcf4111be8a",
        )

        i2c_sensor = SensorConfig(
            "sensor", "future", "i2c_main", 1000, "room", True, address=0x76
        )
        i2c_bus = BusConfig(
            "i2c_main", "i2c", Path("/dev/i2c-1"), timeout_ms=100, retries=2
        )
        self.assertEqual(
            _fingerprint(i2c_sensor, i2c_bus),
            "f580b7a449eb664e076c16322aaeeb9d37c92243df7c043342923aa274963927",
        )
