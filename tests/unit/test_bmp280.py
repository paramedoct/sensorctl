from __future__ import annotations

import struct
import unittest
from unittest.mock import patch

from config import ConfigError, SensorConfig
from drivers.bmp280 import BMP280Driver
from transports.base import Transport

CALIBRATION = struct.pack(
    "<HhhHhhhhhhhh",
    27504,
    26435,
    -1000,
    36477,
    -10685,
    3024,
    2855,
    140,
    -7,
    15500,
    -14600,
    6000,
)
RAW_SAMPLE = bytes.fromhex("655ac07eed00")


class FakeI2CTransport(Transport):
    def __init__(self, chip_id: int = 0x58) -> None:
        self.chip_id = chip_id
        self.transactions: list[tuple[int, bytes, int]] = []

    def open(self) -> None:
        pass

    def close(self) -> None:
        pass

    def transfer(self, address: int, write: bytes, read_length: int) -> bytes:
        self.transactions.append((address, write, read_length))
        if write == b"\xd0":
            return bytes((self.chip_id,))
        if write == b"\xf3":
            return b"\x00"
        if write == b"\x88":
            return CALIBRATION
        if write == b"\xf7":
            return RAW_SAMPLE
        return b""


def make_sensor(**options: object) -> SensorConfig:
    return SensorConfig(
        id="environment",
        driver="bmp280",
        bus="i2c_main",
        address=0x76,
        interval_ms=1000,
        location="office",
        enabled=True,
        options=options,
    )


class BMP280DriverTest(unittest.TestCase):
    @patch("drivers.bmp280.time.sleep")
    def test_compensates_datasheet_sample(self, sleep: object) -> None:
        del sleep
        transport = FakeI2CTransport()
        driver = BMP280Driver(make_sensor())

        driver.initialize(transport)
        sample = driver.read(transport)

        self.assertAlmostEqual(sample["temperature"], 25.08, places=2)
        self.assertAlmostEqual(sample["pressure"], 100653.27, places=2)
        self.assertIn((0x76, b"\xf4\x25", 0), transport.transactions)

    def test_rejects_unexpected_chip(self) -> None:
        driver = BMP280Driver(make_sensor())
        with self.assertRaisesRegex(RuntimeError, "unexpected BMP280 chip ID"):
            driver.initialize(FakeI2CTransport(chip_id=0x60))

    def test_rejects_invalid_address(self) -> None:
        sensor = make_sensor()
        invalid = SensorConfig(**{**sensor.__dict__, "address": 0x75})
        with self.assertRaisesRegex(ConfigError, "0x76 or 0x77"):
            BMP280Driver(invalid)

    def test_rejects_invalid_options(self) -> None:
        with self.assertRaisesRegex(ConfigError, "must be one of"):
            BMP280Driver(make_sensor(pressure_oversampling=3))
        with self.assertRaisesRegex(ConfigError, "unknown bmp280 option"):
            BMP280Driver(make_sensor(mode="normal"))

    def test_requires_initialization(self) -> None:
        with self.assertRaisesRegex(RuntimeError, "not initialized"):
            BMP280Driver(make_sensor()).read(FakeI2CTransport())
