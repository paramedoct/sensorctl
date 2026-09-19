from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from types import MappingProxyType

from sensors.config import AppConfig, ConfigError, SensorConfig
from sensors.drivers.base import SensorDriver
from sensors.drivers.bmp280 import BMP280Driver
from sensors.drivers.mock import MockDriver

DriverFactory = Callable[[SensorConfig], SensorDriver]


@dataclass(frozen=True)
class PreparedDrivers:
    sensors: tuple[SensorConfig, ...]
    by_sensor_id: Mapping[str, SensorDriver]


class DriverRegistry:
    def __init__(self, factories: Mapping[str, DriverFactory] | None = None) -> None:
        self._factories = dict(
            factories or {"bmp280": BMP280Driver, "mock": MockDriver}
        )

    def _create(self, sensor: SensorConfig) -> SensorDriver:
        factory = self._factories.get(sensor.driver)
        if factory is None:
            raise ConfigError(f"unknown driver: {sensor.driver}")
        return factory(sensor)

    def prepare(self, config: AppConfig) -> PreparedDrivers:
        sensors: list[SensorConfig] = []
        drivers: dict[str, SensorDriver] = {}
        for sensor in config.sensors:
            driver = self._create(sensor)
            bus = config.buses[sensor.bus]
            if bus.type not in driver.supported_bus_types:
                raise ConfigError(
                    f"driver {sensor.driver} does not support {bus.type} bus"
                )
            names = [definition.name for definition in driver.fields]
            if not names or len(names) != len(set(names)):
                raise ConfigError(f"driver {sensor.driver} has invalid fields")
            if any(
                not definition.name or not definition.unit
                for definition in driver.fields
            ):
                raise ConfigError(f"driver {sensor.driver} has invalid field metadata")
            if sensor.enabled:
                sensors.append(sensor)
                drivers[sensor.id] = driver
        return PreparedDrivers(tuple(sensors), MappingProxyType(drivers))
