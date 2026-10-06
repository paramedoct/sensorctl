from __future__ import annotations

import sqlite3
from collections.abc import Mapping, Sequence

from sensorctl.model import Sample, StoredSensor


def write_samples(
    connection: sqlite3.Connection,
    samples: Sequence[Sample],
    stored: Mapping[str, StoredSensor],
) -> None:
    for sample in samples:
        sensor = stored[sample.sensor_id]
        cursor = connection.execute(
            """INSERT INTO sample
               (sensor_instance_id, time, monotonic_ms, boot_id)
               VALUES (?, ?, ?, ?)""",
            (sensor.instance_id, sample.time, sample.monotonic_ms, sample.boot_id),
        )
        if cursor.lastrowid is None:
            raise RuntimeError("database did not return a sample id")
        connection.executemany(
            "INSERT INTO measurement (sample_id, field_id, value) VALUES (?, ?, ?)",
            [
                (cursor.lastrowid, sensor.fields[name], value)
                for name, value in sample.values.items()
            ],
        )
