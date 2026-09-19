# sensors

`sensors` is a lightweight time-series collector for Raspberry Pi Zero 2 W.
It schedules configured sensor drivers, accesses I2C, SPI, and UART devices,
and stores numeric measurements in SQLite.

The first release includes a deterministic mock driver and production
transport adapters. Hardware-specific drivers can be added to the static
driver registry.

## Requirements

- Raspberry Pi OS Trixie, 32-bit or 64-bit
- Python 3.13 or newer
- `python3-venv`
- `python3-setuptools`
- Protocol packages as needed:
  - `python3-smbus2`
  - `python3-spidev`
  - `python3-serial`

## Install

```bash
sudo ./install
sudo editor /etc/sensors/sensors.toml
sudo sensorctl validate
sudo sensorctl enable
```

Installation does not enable or start the service. Once enabled, the service
starts automatically on every boot.

## Commands

```bash
sensorctl validate
sensorctl status
sensorctl diagnose
sensorctl start
sensorctl stop
sensorctl restart
sensorctl enable
sensorctl disable
```

Configuration changes take effect after validation and restart.

## Database export

Stop collection before copying the database so the SQLite file and its WAL
cannot be separated.

```bash
sudo sensorctl stop
sudo cp /var/lib/sensors/sensors.db /path/to/export/
sudo sensorctl start
```

## Development

```bash
python3 -m unittest discover -s tests
ruff check .
ruff format --check .
mypy --strict .
shellcheck sensorctl install uninstall utils/*.sh
```
