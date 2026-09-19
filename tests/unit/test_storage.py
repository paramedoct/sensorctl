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
from sensors.storage.database import Database


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
            config, {"counter": DriverRegistry().create(config.sensors[0])}
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
        database.register_sensors(
            first, {"counter": DriverRegistry().create(first.sensors[0])}
        )
        database.register_sensors(
            second, {"counter": DriverRegistry().create(second.sensors[0])}
        )
        database.close()
        connection = sqlite3.connect(self.path)
        count = connection.execute("SELECT COUNT(*) FROM sensor_instance").fetchone()
        connection.close()
        self.assertEqual(count, (2,))
