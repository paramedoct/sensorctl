from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass


@dataclass(frozen=True)
class FieldDefinition:
    name: str
    unit: str


@dataclass(frozen=True)
class Sample:
    sensor_id: str
    time: str
    monotonic_ms: int
    boot_id: str
    values: Mapping[str, float]


@dataclass(frozen=True)
class StoredSensor:
    instance_id: int
    fields: Mapping[str, int]
