from __future__ import annotations

import hashlib
import json
import sqlite3
from collections.abc import Mapping, Sequence
from datetime import datetime

from config import AppConfig, BusConfig, SensorConfig
from model import FieldDefinition, StoredSensor


def register_sensors(
    connection: sqlite3.Connection,
    config: AppConfig,
    fields_by_sensor: Mapping[str, Sequence[FieldDefinition]],
) -> dict[str, StoredSensor]:
    stored: dict[str, StoredSensor] = {}
    for sensor in config.sensors:
        if not sensor.enabled:
            continue
        fingerprint = _fingerprint(sensor, config.buses[sensor.bus])
        row = connection.execute(
            "SELECT id FROM sensor_instance "
            "WHERE logical_id = ? AND config_fingerprint = ?",
            (sensor.id, fingerprint),
        ).fetchone()
        if row is None:
            cursor = connection.execute(
                """INSERT INTO sensor_instance
                   (logical_id, driver, bus_id, location, config_fingerprint,
                    created_at)
                   VALUES (?, ?, ?, ?, ?, ?)""",
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
            connection.executemany(
                "INSERT INTO field (sensor_instance_id, name, unit) VALUES (?, ?, ?)",
                [
                    (instance_id, field.name, field.unit)
                    for field in fields_by_sensor[sensor.id]
                ],
            )
        else:
            instance_id = int(row[0])
        field_rows = connection.execute(
            "SELECT id, name FROM field WHERE sensor_instance_id = ?", (instance_id,)
        ).fetchall()
        stored[sensor.id] = StoredSensor(
            instance_id, {str(name): int(field_id) for field_id, name in field_rows}
        )
    return stored


def _fingerprint(sensor: SensorConfig, bus: BusConfig) -> str:
    payload = {
        "address": sensor.address,
        "bus": {"id": sensor.bus, "type": bus.type, "values": bus.fingerprint_values()},
        "driver": sensor.driver,
        "location": sensor.location,
        "options": dict(sensor.options),
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()


def _local_now() -> str:
    return datetime.now().isoformat(sep=" ", timespec="milliseconds")
