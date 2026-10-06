from __future__ import annotations

from config import BusConfig
from hw.transports.base import Transport
from hw.transports.mock import MockTransport


def create_transport(config: BusConfig) -> Transport:
    if config.type == "mock":
        return MockTransport()
    if config.type == "i2c":
        from hw.transports.i2c import I2CTransport

        return I2CTransport(config)
    if config.type == "spi":
        from hw.transports.spi import SPITransport

        return SPITransport(config)
    from hw.transports.uart import UARTTransport

    return UARTTransport(config)
