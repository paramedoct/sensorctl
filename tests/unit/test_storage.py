from __future__ import annotations

import sqlite3
import tempfile
import unittest
from pathlib import Path

from config import BusConfig, SensorConfig
from drivers.registry import DriverRegistry
from model import Sample
from storage.database import Database, _fingerprint
from tests.support import make_mock_config


class DatabaseTest(unittest.TestCase):
    def setUp(self) -> None:
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.path = Path(self.directory.name) / "db"

    def test_writes_grouped_sample(self) -> None:
        config = make_mock_config(self.path)
        with Database(self.path) as database:
            stored = database.register_sensors(
                config, DriverRegistry().prepare(config).by_sensor_id
            )
            database.write_samples(
                [
                    Sample(
                        "counter",
                        "2026-09-20 12:34:56.789",
                        20,
                        "boot",
                        {"value": 4.0},
                    )
                ],
                stored,
            )
        connection = sqlite3.connect(self.path)
        row = connection.execute(
            """
            SELECT sample.time, measurement.value
            FROM sample JOIN measurement ON measurement.sample_id = sample.id
            """
        ).fetchone()
        connection.close()
        self.assertEqual(row, ("2026-09-20 12:34:56.789", 4.0))

    def test_configuration_change_creates_revision(self) -> None:
        first = make_mock_config(self.path)
        second = make_mock_config(self.path, location="other")
        with Database(self.path) as database:
            database.register_sensors(
                first, DriverRegistry().prepare(first).by_sensor_id
            )
            database.register_sensors(
                second, DriverRegistry().prepare(second).by_sensor_id
            )
        connection = sqlite3.connect(self.path)
        count = connection.execute("SELECT COUNT(*) FROM sensor_instance").fetchone()
        connection.close()
        self.assertEqual(count, (2,))

    def test_migrates_nanosecond_timestamps_to_local_milliseconds(self) -> None:
        connection = sqlite3.connect(self.path)
        connection.executescript(
            """
            CREATE TABLE schema_version (version INTEGER NOT NULL);
            INSERT INTO schema_version VALUES (1);
            CREATE TABLE sensor_instance (
                id INTEGER PRIMARY KEY,
                logical_id TEXT NOT NULL,
                driver TEXT NOT NULL,
                bus_id TEXT NOT NULL,
                location TEXT NOT NULL,
                config_fingerprint TEXT NOT NULL,
                created_at_ns INTEGER NOT NULL,
                UNIQUE (logical_id, config_fingerprint)
            );
            CREATE TABLE field (
                id INTEGER PRIMARY KEY,
                sensor_instance_id INTEGER NOT NULL REFERENCES sensor_instance(id),
                name TEXT NOT NULL,
                unit TEXT NOT NULL,
                UNIQUE (sensor_instance_id, name)
            );
            CREATE TABLE sample (
                id INTEGER PRIMARY KEY,
                sensor_instance_id INTEGER NOT NULL REFERENCES sensor_instance(id),
                wall_time_ns INTEGER NOT NULL,
                monotonic_ns INTEGER NOT NULL,
                boot_id TEXT NOT NULL
            );
            CREATE INDEX sample_sensor_time_idx
            ON sample (sensor_instance_id, wall_time_ns);
            CREATE TABLE measurement (
                sample_id INTEGER NOT NULL REFERENCES sample(id) ON DELETE CASCADE,
                field_id INTEGER NOT NULL REFERENCES field(id),
                value REAL NOT NULL,
                PRIMARY KEY (sample_id, field_id)
            );
            INSERT INTO sensor_instance
            VALUES (1, 'sensor', 'mock', 'bus', 'room', 'hash', 2345000000);
            INSERT INTO field VALUES (1, 1, 'value', 'count');
            INSERT INTO sample VALUES (1, 1, 1234000000, 5678000000, 'boot');
            INSERT INTO measurement VALUES (1, 1, 4.0);
            """
        )
        connection.close()

        with Database(self.path):
            pass

        connection = sqlite3.connect(self.path)
        version = connection.execute("SELECT version FROM schema_version").fetchone()
        sample = connection.execute(
            "SELECT time, monotonic_ms FROM sample"
        ).fetchone()
        types = {
            row[1]: row[2]
            for row in connection.execute("PRAGMA table_info(sample)").fetchall()
        }
        connection.close()
        self.assertEqual(version, (2,))
        self.assertIsNotNone(sample)
        assert sample is not None
        self.assertRegex(
            sample[0], r"^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:01\.234$"
        )
        self.assertEqual(sample[1], 5678)
        self.assertEqual(types["time"], "TEXT")

    def test_context_manager_closes_connection(self) -> None:
        database = Database(self.path)
        with database:
            pass
        config = make_mock_config(self.path)
        with self.assertRaisesRegex(RuntimeError, "database is not open"):
            database.register_sensors(
                config,
                DriverRegistry().prepare(config).by_sensor_id,
            )

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
