from __future__ import annotations

from sensorctl.config import BusConfig
from sensorctl.hw.transports.base import Transport
from sensorctl.hw.transports.mock import MockTransport


def create_transport(config: BusConfig) -> Transport:
    if config.type == "mock":
        return MockTransport()
    if config.type == "i2c":
        from sensorctl.hw.transports.i2c import I2CTransport

        return I2CTransport(config)
    if config.type == "spi":
        from sensorctl.hw.transports.spi import SPITransport

        return SPITransport(config)
    from sensorctl.hw.transports.uart import UARTTransport

    return UARTTransport(config)
