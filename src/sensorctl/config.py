from __future__ import annotations

import tomllib
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Final, Literal, cast

BusType = Literal["i2c", "spi", "uart", "mock"]

_TOP_LEVEL: Final = {"version", "collector", "database", "buses", "sensors"}
_COLLECTOR_KEYS: Final = {
    "queue_size",
    "batch_size",
    "flush_interval_ms",
    "status_interval_ms",
    "shutdown_timeout_s",
}
_DATABASE_KEYS: Final = {"path"}
_SENSOR_KEYS: Final = {
    "id",
    "driver",
    "bus",
    "address",
    "interval_ms",
    "location",
    "enabled",
    "options",
}
_BUS_KEYS: Final[dict[str, set[str]]] = {
    "i2c": {"type", "device", "timeout_ms", "retries"},
    "spi": {"type", "device", "mode", "max_speed_hz", "timeout_ms", "retries"},
    "uart": {"type", "device", "baud_rate", "timeout_ms", "retries"},
    "mock": {"type"},
}


class ConfigError(ValueError):
    """Raised when the configuration contract is violated."""


@dataclass(frozen=True)
class CollectorConfig:
    queue_size: int = 1000
    batch_size: int = 100
    flush_interval_ms: int = 1000
    status_interval_ms: int = 1000
    shutdown_timeout_s: int = 10


@dataclass(frozen=True)
class DatabaseConfig:
    path: Path = Path("/var/lib/sensorctl/sensorctl.db")


@dataclass(frozen=True)
class BusConfig:
    id: str
    type: BusType
    device: Path | None = None
    timeout_ms: int = 100
    retries: int = 0
    mode: int = 0
    max_speed_hz: int = 1_000_000
    baud_rate: int = 9600

    def require_device(self) -> Path:
        if self.device is None:
            raise ConfigError(f"bus {self.id} does not have a device")
        return self.device

    def fingerprint_values(self) -> dict[str, object]:
        if self.type == "mock":
            return {}
        values: dict[str, object] = {
            "device": str(self.require_device()),
            "timeout_ms": self.timeout_ms,
            "retries": self.retries,
        }
        if self.type == "spi":
            values.update(mode=self.mode, max_speed_hz=self.max_speed_hz)
        elif self.type == "uart":
            values["baud_rate"] = self.baud_rate
        return values


@dataclass(frozen=True)
class SensorConfig:
    id: str
    driver: str
    bus: str
    interval_ms: int
    location: str
    enabled: bool
    address: int | None = None
    options: Mapping[str, object] = field(default_factory=dict)


@dataclass(frozen=True)
class AppConfig:
    version: int
    collector: CollectorConfig
    database: DatabaseConfig
    buses: Mapping[str, BusConfig]
    sensors: tuple[SensorConfig, ...]


def _table(value: object, name: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ConfigError(f"{name} must be a table")
    return cast(dict[str, Any], value)


def _reject_unknown(values: Mapping[str, object], allowed: set[str], name: str) -> None:
    unknown = sorted(set(values) - allowed)
    if unknown:
        raise ConfigError(f"unknown {name} key: {unknown[0]}")


def _integer(
    values: Mapping[str, object], name: str, default: int, minimum: int, maximum: int
) -> int:
    value = values.get(name, default)
    if not isinstance(value, int) or isinstance(value, bool):
        raise ConfigError(f"{name} must be an integer")
    if not minimum <= value <= maximum:
        raise ConfigError(f"{name} must be between {minimum} and {maximum}")
    return value


def _string(values: Mapping[str, object], name: str) -> str:
    value = values.get(name)
    if not isinstance(value, str) or not value:
        raise ConfigError(f"{name} must be a non-empty string")
    return value


def _load_collector(raw: object) -> CollectorConfig:
    values = _table(raw, "collector")
    _reject_unknown(values, _COLLECTOR_KEYS, "collector")
    return CollectorConfig(
        queue_size=_integer(values, "queue_size", 1000, 1, 1_000_000),
        batch_size=_integer(values, "batch_size", 100, 1, 100_000),
        flush_interval_ms=_integer(values, "flush_interval_ms", 1000, 10, 60_000),
        status_interval_ms=_integer(values, "status_interval_ms", 1000, 100, 60_000),
        shutdown_timeout_s=_integer(values, "shutdown_timeout_s", 10, 1, 10),
    )


def _load_bus(bus_id: str, raw: object) -> BusConfig:
    values = _table(raw, f"bus {bus_id}")
    bus_type = values.get("type")
    if not isinstance(bus_type, str) or bus_type not in _BUS_KEYS:
        raise ConfigError(f"bus {bus_id} has unsupported type")
    _reject_unknown(values, _BUS_KEYS[bus_type], f"bus {bus_id}")
    typed_bus = cast(BusType, bus_type)
    if typed_bus == "mock":
        return BusConfig(bus_id, typed_bus)
    device_value = _string(values, "device")
    if not device_value.startswith("/dev/"):
        raise ConfigError(f"bus {bus_id} device must be under /dev")
    device = Path(device_value)
    if typed_bus == "i2c" and (
        not device.name.startswith("i2c-")
        or not device.name.removeprefix("i2c-").isdigit()
    ):
        raise ConfigError(f"bus {bus_id} has an invalid I2C device")
    if typed_bus == "spi":
        suffix = device.name.removeprefix("spidev")
        if not device.name.startswith("spidev") or len(suffix.split(".")) != 2:
            raise ConfigError(f"bus {bus_id} has an invalid SPI device")
        if not all(part.isdigit() for part in suffix.split(".")):
            raise ConfigError(f"bus {bus_id} has an invalid SPI device")
    return BusConfig(
        id=bus_id,
        type=typed_bus,
        device=device,
        timeout_ms=_integer(values, "timeout_ms", 100, 1, 60_000),
        retries=_integer(values, "retries", 2, 0, 100),
        mode=_integer(values, "mode", 0, 0, 3) if typed_bus == "spi" else 0,
        max_speed_hz=(
            _integer(values, "max_speed_hz", 1_000_000, 1, 125_000_000)
            if typed_bus == "spi"
            else 1_000_000
        ),
        baud_rate=(
            _integer(values, "baud_rate", 9600, 1, 4_000_000)
            if typed_bus == "uart"
            else 9600
        ),
    )


def _load_sensor(raw: object) -> SensorConfig:
    values = _table(raw, "sensor")
    _reject_unknown(values, _SENSOR_KEYS, "sensor")
    enabled = values.get("enabled", True)
    if not isinstance(enabled, bool):
        raise ConfigError("sensor enabled must be a boolean")
    address = values.get("address")
    if address is not None and (
        not isinstance(address, int)
        or isinstance(address, bool)
        or not 0 <= address <= 0x7F
    ):
        raise ConfigError("sensor address must be between 0x00 and 0x7f")
    options = _table(values.get("options", {}), "sensor options")
    return SensorConfig(
        id=_string(values, "id"),
        driver=_string(values, "driver"),
        bus=_string(values, "bus"),
        interval_ms=_integer(values, "interval_ms", 1000, 10, 86_400_000),
        location=_string(values, "location"),
        enabled=enabled,
        address=address,
        options=options,
    )


def _validate_collisions(config: AppConfig) -> None:
    ids: set[str] = set()
    i2c_addresses: set[tuple[str, int]] = set()
    devices: dict[tuple[str, Path], str] = {}
    exclusive_buses: dict[str, str] = {}
    for bus in config.buses.values():
        device = bus.device
        if device is not None and bus.type in {"spi", "uart"}:
            device_key = (bus.type, device)
            if device_key in devices:
                raise ConfigError(
                    f"buses {devices[device_key]} and {bus.id} share "
                    f"{bus.type} device {device}"
                )
            devices[device_key] = bus.id
    for sensor in config.sensors:
        if sensor.id in ids:
            raise ConfigError(f"duplicate sensor id: {sensor.id}")
        ids.add(sensor.id)
        configured_bus = config.buses.get(sensor.bus)
        if configured_bus is None:
            raise ConfigError(f"sensor {sensor.id} references unknown bus {sensor.bus}")
        if configured_bus.type == "i2c":
            if sensor.address is None:
                raise ConfigError(f"sensor {sensor.id} requires an I2C address")
            address_key = (sensor.bus, sensor.address)
            if address_key in i2c_addresses:
                raise ConfigError(
                    f"sensor {sensor.id} has a duplicate I2C address on {sensor.bus}"
                )
            i2c_addresses.add(address_key)
        elif sensor.address is not None:
            raise ConfigError(f"sensor {sensor.id} address is only valid for I2C")
        if configured_bus.type in {"spi", "uart"}:
            if sensor.bus in exclusive_buses:
                raise ConfigError(
                    f"sensors {exclusive_buses[sensor.bus]} and {sensor.id} "
                    f"share exclusive bus {sensor.bus}"
                )
            exclusive_buses[sensor.bus] = sensor.id


def load_config(path: Path) -> AppConfig:
    try:
        with path.open("rb") as stream:
            raw = tomllib.load(stream)
    except (OSError, tomllib.TOMLDecodeError) as error:
        raise ConfigError(f"cannot load {path}: {error}") from error
    _reject_unknown(raw, _TOP_LEVEL, "top-level")
    version = raw.get("version")
    if version != 1:
        raise ConfigError("version must be 1")
    database = _table(raw.get("database", {}), "database")
    _reject_unknown(database, _DATABASE_KEYS, "database")
    database_path = database.get("path", "/var/lib/sensorctl/sensorctl.db")
    if not isinstance(database_path, str) or not database_path.startswith("/"):
        raise ConfigError("database path must be absolute")
    buses_raw = _table(raw.get("buses", {}), "buses")
    buses = {name: _load_bus(name, value) for name, value in buses_raw.items()}
    sensors_raw = raw.get("sensors", [])
    if not isinstance(sensors_raw, list):
        raise ConfigError("sensors must be an array of tables")
    config = AppConfig(
        version=1,
        collector=_load_collector(raw.get("collector", {})),
        database=DatabaseConfig(Path(database_path)),
        buses=buses,
        sensors=tuple(_load_sensor(value) for value in sensors_raw),
    )
    if not config.sensors:
        raise ConfigError("at least one sensor is required")
    _validate_collisions(config)
    return config
