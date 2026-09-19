from __future__ import annotations

from typing import Any, cast

from sensors.config import BusConfig
from sensors.transports.base import Transport


class SPITransport(Transport):
    def __init__(self, config: BusConfig) -> None:
        self._device = str(config.values["device"])
        self._mode = cast(int, config.values["mode"])
        self._speed = cast(int, config.values["max_speed_hz"])
        self._spi: Any | None = None

    def open(self) -> None:
        try:
            import spidev  # type: ignore[import-not-found]
        except ImportError as error:
            raise RuntimeError("SPI requires the python3-spidev package") from error
        name = self._device.rsplit("/", 1)[-1]
        bus, device = (int(part) for part in name.removeprefix("spidev").split("."))
        spi = spidev.SpiDev()
        spi.open(bus, device)
        spi.mode = self._mode
        spi.max_speed_hz = self._speed
        self._spi = spi

    def transfer(self, data: bytes) -> bytes:
        if self._spi is None:
            raise RuntimeError("SPI transport is not open")
        return bytes(self._spi.xfer2(list(data)))

    def close(self) -> None:
        if self._spi is not None:
            self._spi.close()
            self._spi = None
