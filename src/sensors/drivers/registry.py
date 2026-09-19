from __future__ import annotations

from collections.abc import Callable

from sensors.config import AppConfig, ConfigError, SensorConfig
from sensors.drivers.base import SensorDriver
from sensors.drivers.mock import MockDriver

DriverFactory = Callable[[SensorConfig], SensorDriver]


class DriverRegistry:
    def __init__(self) -> None:
        self._factories: dict[str, DriverFactory] = {"mock": MockDriver}

    def create(self, sensor: SensorConfig) -> SensorDriver:
        factory = self._factories.get(sensor.driver)
        if factory is None:
            raise ConfigError(f"unknown driver: {sensor.driver}")
        return factory(sensor)

    def validate(self, config: AppConfig) -> None:
        for sensor in config.sensors:
            driver = self.create(sensor)
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
