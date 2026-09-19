from __future__ import annotations

import hashlib
import json
import sqlite3
import time
from collections.abc import Mapping
from importlib.resources import files
from pathlib import Path
from types import TracebackType
from typing import Self

from sensors.config import AppConfig, BusConfig, SensorConfig
from sensors.drivers.base import SensorDriver
from sensors.model import Sample, StoredSensor


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
        schema = files("sensors.storage").joinpath("schema.sql").read_text()
        connection.executescript(schema)
        version = connection.execute("SELECT version FROM schema_version").fetchone()
        if version != (1,):
            connection.close()
            raise RuntimeError("unsupported database schema version")
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
                         config_fingerprint, created_at_ns)
                    VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (
                        sensor.id,
                        sensor.driver,
                        sensor.bus,
                        sensor.location,
                        fingerprint,
                        time.time_ns(),
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
                        (sensor_instance_id, wall_time_ns, monotonic_ns, boot_id)
                    VALUES (?, ?, ?, ?)
                    """,
                    (
                        sensor.instance_id,
                        sample.wall_time_ns,
                        sample.monotonic_ns,
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
