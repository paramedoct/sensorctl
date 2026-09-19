from __future__ import annotations

from typing import Any

from sensors.config import BusConfig
from sensors.transports.base import Transport


class I2CTransport(Transport):
    def __init__(self, config: BusConfig) -> None:
        self._device = config.require_device()
        self._bus: Any | None = None

    def open(self) -> None:
        try:
            from smbus2 import SMBus  # type: ignore[import-not-found]
        except ImportError as error:
            raise RuntimeError("I2C requires the python3-smbus2 package") from error
        bus_number = int(self._device.name.removeprefix("i2c-"))
        self._bus = SMBus(bus_number)

    def transfer(self, address: int, write: bytes, read_length: int) -> bytes:
        if self._bus is None:
            raise RuntimeError("I2C transport is not open")
        from smbus2 import i2c_msg

        messages: list[Any] = []
        if write:
            messages.append(i2c_msg.write(address, write))
        read_message = None
        if read_length:
            read_message = i2c_msg.read(address, read_length)
            messages.append(read_message)
        self._bus.i2c_rdwr(*messages)
        return bytes(read_message) if read_message is not None else b""

    def close(self) -> None:
        if self._bus is not None:
            self._bus.close()
            self._bus = None
