from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Mapping

from sensorctl.config import SensorConfig
from sensorctl.model import FieldDefinition
from sensorctl.transports.base import Transport


class SensorDriver(ABC):
    fields: tuple[FieldDefinition, ...]
    supported_bus_types: frozenset[str]

    def __init__(self, sensor: SensorConfig) -> None:
        self.sensor = sensor

    @abstractmethod
    def validate_options(self, options: Mapping[str, object]) -> None:
        """Validate driver-specific configuration."""

    @abstractmethod
    def initialize(self, transport: Transport) -> None:
        """Initialize hardware state."""

    @abstractmethod
    def read(self, transport: Transport) -> Mapping[str, float]:
        """Read one complete sample."""

    def close(self) -> None:
        """Release driver-owned resources."""
        return None
