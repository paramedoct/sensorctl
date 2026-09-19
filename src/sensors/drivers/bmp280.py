from __future__ import annotations

import struct
import time
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Final, cast

from sensors.config import ConfigError, SensorConfig
from sensors.drivers.base import SensorDriver
from sensors.model import FieldDefinition
from sensors.transports.base import Transport
from sensors.transports.i2c import I2CDevice

_CHIP_ID_REGISTER: Final = 0xD0
_EXPECTED_CHIP_ID: Final = 0x58
_STATUS_REGISTER: Final = 0xF3
_CONTROL_REGISTER: Final = 0xF4
_CALIBRATION_REGISTER: Final = 0x88
_DATA_REGISTER: Final = 0xF7
_STATUS_BUSY_MASK: Final = 0x09
_READY_TIMEOUT_S: Final = 0.1
_OVERSAMPLING_CODES: Final = {1: 1, 2: 2, 4: 3, 8: 4, 16: 5}


@dataclass(frozen=True)
class _Calibration:
    t1: int
    t2: int
    t3: int
    p1: int
    p2: int
    p3: int
    p4: int
    p5: int
    p6: int
    p7: int
    p8: int
    p9: int


class BMP280Driver(SensorDriver):
    fields = (
        FieldDefinition("temperature", "deg_c"),
        FieldDefinition("pressure", "pa"),
    )
    supported_bus_types = frozenset({"i2c"})

    def __init__(self, sensor: SensorConfig) -> None:
        super().__init__(sensor)
        self.validate_options(sensor.options)
        if sensor.address not in {0x76, 0x77}:
            raise ConfigError("bmp280 address must be 0x76 or 0x77")
        self._address = sensor.address
        self._temperature_oversampling = self._oversampling_option(
            sensor.options, "temperature_oversampling"
        )
        self._pressure_oversampling = self._oversampling_option(
            sensor.options, "pressure_oversampling"
        )
        self._calibration: _Calibration | None = None

    def validate_options(self, options: Mapping[str, object]) -> None:
        allowed = {"temperature_oversampling", "pressure_oversampling"}
        unknown = sorted(set(options) - allowed)
        if unknown:
            raise ConfigError(f"unknown bmp280 option: {unknown[0]}")
        for name in allowed:
            self._oversampling_option(options, name)

    def initialize(self, transport: Transport) -> None:
        device = self._require_i2c(transport)
        chip_id = self._read_register(device, _CHIP_ID_REGISTER, 1)[0]
        if chip_id != _EXPECTED_CHIP_ID:
            raise RuntimeError(f"unexpected BMP280 chip ID: 0x{chip_id:02x}")
        self._wait_until_ready(device)
        calibration = self._read_register(device, _CALIBRATION_REGISTER, 24)
        self._calibration = _Calibration(*struct.unpack("<HhhHhhhhhhhh", calibration))

    def read(self, transport: Transport) -> Mapping[str, float]:
        device = self._require_i2c(transport)
        calibration = self._calibration
        if calibration is None:
            raise RuntimeError("BMP280 driver is not initialized")

        control = (
            _OVERSAMPLING_CODES[self._temperature_oversampling] << 5
            | _OVERSAMPLING_CODES[self._pressure_oversampling] << 2
            | 0x01
        )
        self._write_register(device, _CONTROL_REGISTER, control)
        time.sleep(self._maximum_measurement_time_s())
        self._wait_until_ready(device)

        raw = self._read_register(device, _DATA_REGISTER, 6)
        raw_pressure = raw[0] << 12 | raw[1] << 4 | raw[2] >> 4
        raw_temperature = raw[3] << 12 | raw[4] << 4 | raw[5] >> 4
        temperature, fine_temperature = self._compensate_temperature(
            raw_temperature, calibration
        )
        pressure = self._compensate_pressure(
            raw_pressure, fine_temperature, calibration
        )
        return {"temperature": temperature, "pressure": pressure}

    @staticmethod
    def _oversampling_option(options: Mapping[str, object], name: str) -> int:
        value = options.get(name, 1)
        if not isinstance(value, int) or isinstance(value, bool):
            raise ConfigError(f"bmp280 option {name} must be an integer")
        if value not in _OVERSAMPLING_CODES:
            raise ConfigError(f"bmp280 option {name} must be one of 1, 2, 4, 8, 16")
        return value

    @staticmethod
    def _require_i2c(transport: Transport) -> I2CDevice:
        if not isinstance(transport, I2CDevice):
            raise TypeError("BMP280 requires an I2C transport")
        return cast(I2CDevice, transport)

    def _read_register(self, device: I2CDevice, register: int, length: int) -> bytes:
        data = device.transfer(self._address, bytes((register,)), length)
        if len(data) != length:
            message = (
                f"BMP280 register 0x{register:02x} returned "
                f"{len(data)} of {length} bytes"
            )
            raise RuntimeError(message)
        return data

    def _write_register(self, device: I2CDevice, register: int, value: int) -> None:
        device.transfer(self._address, bytes((register, value)), 0)

    def _wait_until_ready(self, device: I2CDevice) -> None:
        deadline = time.monotonic() + _READY_TIMEOUT_S
        while self._read_register(device, _STATUS_REGISTER, 1)[0] & _STATUS_BUSY_MASK:
            if time.monotonic() >= deadline:
                raise TimeoutError("BMP280 did not become ready")
            time.sleep(0.001)

    def _maximum_measurement_time_s(self) -> float:
        typical_ms = (
            1.25
            + 2.3 * self._temperature_oversampling
            + 2.3 * self._pressure_oversampling
            + 0.575
        )
        return (typical_ms * 1.15 + 0.5) / 1000.0

    @staticmethod
    def _compensate_temperature(
        raw: int, calibration: _Calibration
    ) -> tuple[float, float]:
        first = (raw / 16384.0 - calibration.t1 / 1024.0) * calibration.t2
        second = (raw / 131072.0 - calibration.t1 / 8192.0) ** 2 * calibration.t3
        fine_temperature = first + second
        return fine_temperature / 5120.0, fine_temperature

    @staticmethod
    def _compensate_pressure(
        raw: int, fine_temperature: float, calibration: _Calibration
    ) -> float:
        first = fine_temperature / 2.0 - 64000.0
        second = first * first * calibration.p6 / 32768.0
        second += first * calibration.p5 * 2.0
        second = second / 4.0 + calibration.p4 * 65536.0
        first = (
            calibration.p3 * first * first / 524288.0 + calibration.p2 * first
        ) / 524288.0
        first = (1.0 + first / 32768.0) * calibration.p1
        if first == 0.0:
            raise RuntimeError("BMP280 pressure calibration is invalid")
        pressure = (1048576.0 - raw - second / 4096.0) * 6250.0 / first
        first = calibration.p9 * pressure * pressure / 2147483648.0
        second = pressure * calibration.p8 / 32768.0
        return pressure + (first + second + calibration.p7) / 16.0
