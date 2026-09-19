from __future__ import annotations

from typing import Any, cast

from sensors.config import BusConfig
from sensors.transports.base import Transport


class UARTTransport(Transport):
    def __init__(self, config: BusConfig) -> None:
        self._device = str(config.values["device"])
        self._baud_rate = cast(int, config.values["baud_rate"])
        self._timeout = cast(int, config.values["timeout_ms"]) / 1000
        self._serial: Any | None = None

    def open(self) -> None:
        try:
            import serial  # type: ignore[import-untyped]
        except ImportError as error:
            raise RuntimeError("UART requires the python3-serial package") from error
        self._serial = serial.Serial(
            self._device, baudrate=self._baud_rate, timeout=self._timeout
        )

    def read(self, size: int) -> bytes:
        if self._serial is None:
            raise RuntimeError("UART transport is not open")
        return bytes(self._serial.read(size))

    def write(self, data: bytes) -> int:
        if self._serial is None:
            raise RuntimeError("UART transport is not open")
        return int(self._serial.write(data))

    def close(self) -> None:
        if self._serial is not None:
            self._serial.close()
            self._serial = None
