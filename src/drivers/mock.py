from __future__ import annotations

from collections.abc import Mapping
from typing import cast

from config import ConfigError, SensorConfig
from drivers.base import SensorDriver
from model import FieldDefinition
from transports.base import Transport


class MockDriver(SensorDriver):
    fields = (FieldDefinition("value", "count"),)
    supported_bus_types = frozenset({"mock"})

    def __init__(self, sensor: SensorConfig) -> None:
        super().__init__(sensor)
        options = sensor.options
        self.validate_options(options)
        self._value = float(cast(int | float, options.get("start", 0.0)))
        self._step = float(cast(int | float, options.get("step", 1.0)))

    def validate_options(self, options: Mapping[str, object]) -> None:
        unknown = sorted(set(options) - {"start", "step"})
        if unknown:
            raise ConfigError(f"unknown mock option: {unknown[0]}")
        for name in ("start", "step"):
            value = options.get(name, 0)
            if not isinstance(value, (int, float)) or isinstance(value, bool):
                raise ConfigError(f"mock option {name} must be numeric")

    def initialize(self, transport: Transport) -> None:
        del transport

    def read(self, transport: Transport) -> Mapping[str, float]:
        del transport
        value = self._value
        self._value += self._step
        return {"value": value}
