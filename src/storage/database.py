from __future__ import annotations

import hashlib
import json
import sqlite3
from collections.abc import Mapping
from datetime import datetime
from importlib.resources import files
from pathlib import Path
from types import TracebackType
from typing import Self

from config import AppConfig, BusConfig, SensorConfig
from drivers.base import SensorDriver
from model import Sample, StoredSensor


class Database:
    def __init__(self, path: Path) -> None:
        self.path = path
        self._connection: sqlite3.Connection | None = None

    def __enter__(self) -> Self:
        self.open()
        return self

    def __exit__(
        self,
        exception_type: type[BaseException] | None,
        exception: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        del exception, traceback
        self.close(checkpoint=exception_type is None)

    def open(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(self.path, timeout=10)
        connection.execute("PRAGMA journal_mode = WAL")
        connection.execute("PRAGMA synchronous = NORMAL")
        connection.execute("PRAGMA foreign_keys = ON")
        try:
            _prepare_schema(connection)
        except Exception:
            connection.close()
            raise
        self._connection = connection

    def close(self, checkpoint: bool = True) -> None:
        if self._connection is None:
            return
        if checkpoint:
            self._connection.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        self._connection.close()
        self._connection = None

    def register_sensors(
        self,
        config: AppConfig,
        drivers: Mapping[str, SensorDriver],
    ) -> dict[str, StoredSensor]:
        connection = self._require_connection()
        stored: dict[str, StoredSensor] = {}
        for sensor in config.sensors:
            if not sensor.enabled:
                continue
            fingerprint = _fingerprint(sensor, config.buses[sensor.bus])
            row = connection.execute(
                """
                SELECT id FROM sensor_instance
                WHERE logical_id = ? AND config_fingerprint = ?
                """,
                (sensor.id, fingerprint),
            ).fetchone()
            if row is None:
                cursor = connection.execute(
                    """
                    INSERT INTO sensor_instance
                        (logical_id, driver, bus_id, location,
                         config_fingerprint, created_at)
                    VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (
                        sensor.id,
                        sensor.driver,
                        sensor.bus,
                        sensor.location,
                        fingerprint,
                        _local_now(),
                    ),
                )
                if cursor.lastrowid is None:
                    raise RuntimeError("database did not return a sensor instance id")
                instance_id = cursor.lastrowid
                for definition in drivers[sensor.id].fields:
                    connection.execute(
                        """
                        INSERT INTO field (sensor_instance_id, name, unit)
                        VALUES (?, ?, ?)
                        """,
                        (instance_id, definition.name, definition.unit),
                    )
            else:
                instance_id = int(row[0])
            field_rows = connection.execute(
                "SELECT id, name FROM field WHERE sensor_instance_id = ?",
                (instance_id,),
            ).fetchall()
            stored[sensor.id] = StoredSensor(
                instance_id, {str(name): int(field_id) for field_id, name in field_rows}
            )
        connection.commit()
        return stored

    def write_samples(
        self, samples: list[Sample], stored: Mapping[str, StoredSensor]
    ) -> None:
        connection = self._require_connection()
        with connection:
            for sample in samples:
                sensor = stored[sample.sensor_id]
                cursor = connection.execute(
                    """
                    INSERT INTO sample
                        (sensor_instance_id, time, monotonic_ms, boot_id)
                    VALUES (?, ?, ?, ?)
                    """,
                    (
                        sensor.instance_id,
                        sample.time,
                        sample.monotonic_ms,
                        sample.boot_id,
                    ),
                )
                if cursor.lastrowid is None:
                    raise RuntimeError("database did not return a sample id")
                sample_id = cursor.lastrowid
                connection.executemany(
                    """
                    INSERT INTO measurement (sample_id, field_id, value)
                    VALUES (?, ?, ?)
                    """,
                    [
                        (sample_id, sensor.fields[name], value)
                        for name, value in sample.values.items()
                    ],
                )

    def _require_connection(self) -> sqlite3.Connection:
        if self._connection is None:
            raise RuntimeError("database is not open")
        return self._connection


def _fingerprint(sensor: SensorConfig, bus: BusConfig) -> str:
    payload = {
        "address": sensor.address,
        "bus": {
            "id": sensor.bus,
            "type": bus.type,
            "values": bus.fingerprint_values(),
        },
        "driver": sensor.driver,
        "location": sensor.location,
        "options": dict(sensor.options),
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()


def _prepare_schema(connection: sqlite3.Connection) -> None:
    row = connection.execute(
        "SELECT name FROM sqlite_master WHERE type = 'table' AND name = 'schema_version'"
    ).fetchone()
    if row is not None:
        version = connection.execute("SELECT version FROM schema_version").fetchone()
        if version == (1,):
            _migrate_v1(connection)
        elif version != (2,):
            raise RuntimeError("unsupported database schema version")
    schema = files("storage").joinpath("schema.sql").read_text()
    connection.executescript(schema)


def _migrate_v1(connection: sqlite3.Connection) -> None:
    connection.commit()
    connection.execute("PRAGMA foreign_keys = OFF")
    try:
        connection.execute("BEGIN")
        connection.execute("ALTER TABLE measurement RENAME TO measurement_v1")
        connection.execute("ALTER TABLE field RENAME TO field_v1")
        connection.execute("ALTER TABLE sample RENAME TO sample_v1")
        connection.execute("ALTER TABLE sensor_instance RENAME TO sensor_instance_v1")
        connection.execute("DROP INDEX sample_sensor_time_idx")
        connection.execute(
            """
            CREATE TABLE sensor_instance (
                id INTEGER PRIMARY KEY,
                logical_id TEXT NOT NULL,
                driver TEXT NOT NULL,
                bus_id TEXT NOT NULL,
                location TEXT NOT NULL,
                config_fingerprint TEXT NOT NULL,
                created_at TEXT NOT NULL,
                UNIQUE (logical_id, config_fingerprint)
            )
            """
        )
        connection.execute(
            """
            INSERT INTO sensor_instance
                (id, logical_id, driver, bus_id, location,
                 config_fingerprint, created_at)
            SELECT id, logical_id, driver, bus_id, location,
                   config_fingerprint, strftime(
                '%Y-%m-%d %H:%M:%f',
                created_at_ns / 1000000000.0,
                'unixepoch',
                'localtime'
            )
            FROM sensor_instance_v1
            """
        )
        connection.execute(
            """
            CREATE TABLE field (
                id INTEGER PRIMARY KEY,
                sensor_instance_id INTEGER NOT NULL REFERENCES sensor_instance(id),
                name TEXT NOT NULL,
                unit TEXT NOT NULL,
                UNIQUE (sensor_instance_id, name)
            )
            """
        )
        connection.execute(
            """
            INSERT INTO field (id, sensor_instance_id, name, unit)
            SELECT id, sensor_instance_id, name, unit FROM field_v1
            """
        )
        connection.execute(
            """
            CREATE TABLE sample (
                id INTEGER PRIMARY KEY,
                sensor_instance_id INTEGER NOT NULL REFERENCES sensor_instance(id),
                time TEXT NOT NULL,
                monotonic_ms INTEGER NOT NULL,
                boot_id TEXT NOT NULL
            )
            """
        )
        connection.execute(
            """
            INSERT INTO sample
                (id, sensor_instance_id, time, monotonic_ms, boot_id)
            SELECT id, sensor_instance_id, strftime(
                '%Y-%m-%d %H:%M:%f',
                wall_time_ns / 1000000000.0,
                'unixepoch',
                'localtime'
            ), CAST(monotonic_ns / 1000000 AS INTEGER), boot_id
            FROM sample_v1
            """
        )
        connection.execute(
            """
            CREATE TABLE measurement (
                sample_id INTEGER NOT NULL REFERENCES sample(id) ON DELETE CASCADE,
                field_id INTEGER NOT NULL REFERENCES field(id),
                value REAL NOT NULL,
                PRIMARY KEY (sample_id, field_id)
            )
            """
        )
        connection.execute(
            """
            INSERT INTO measurement (sample_id, field_id, value)
            SELECT sample_id, field_id, value FROM measurement_v1
            """
        )
        connection.execute("DROP TABLE measurement_v1")
        connection.execute("DROP TABLE sample_v1")
        connection.execute("DROP TABLE field_v1")
        connection.execute("DROP TABLE sensor_instance_v1")
        connection.execute("UPDATE schema_version SET version = 2")
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.execute("PRAGMA foreign_keys = ON")


def _local_now() -> str:
    return datetime.now().isoformat(sep=" ", timespec="milliseconds")
