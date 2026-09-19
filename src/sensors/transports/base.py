from __future__ import annotations

from abc import ABC, abstractmethod

from sensors.config import BusConfig


class Transport(ABC):
    @abstractmethod
    def open(self) -> None:
        """Open the underlying device."""

    @abstractmethod
    def close(self) -> None:
        """Close the underlying device."""


class MockTransport(Transport):
    def open(self) -> None:
        pass

    def close(self) -> None:
        pass


def create_transport(config: BusConfig) -> Transport:
    if config.type == "mock":
        return MockTransport()
    if config.type == "i2c":
        from sensors.transports.i2c import I2CTransport

        return I2CTransport(config)
    if config.type == "spi":
        from sensors.transports.spi import SPITransport

        return SPITransport(config)
    from sensors.transports.uart import UARTTransport

    return UARTTransport(config)
