from __future__ import annotations

import sqlite3
from collections.abc import Mapping, Sequence
from pathlib import Path
from types import TracebackType
from typing import Self

from config import AppConfig
from model import FieldDefinition, Sample, StoredSensor
from storage.connection import connect
from storage.migration import upgrade_database
from storage.repositories import register_sensors, write_samples
from storage.repositories.sensors import _fingerprint as _fingerprint


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
        upgrade_database(self.path)
        self._connection = connect(self.path)

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
        fields_by_sensor: Mapping[str, Sequence[FieldDefinition]],
    ) -> dict[str, StoredSensor]:
        connection = self._require_connection()
        with connection:
            return register_sensors(connection, config, fields_by_sensor)

    def write_samples(
        self, samples: list[Sample], stored: Mapping[str, StoredSensor]
    ) -> None:
        connection = self._require_connection()
        with connection:
            write_samples(connection, samples, stored)

    def _require_connection(self) -> sqlite3.Connection:
        if self._connection is None:
            raise RuntimeError("database is not open")
        return self._connection
