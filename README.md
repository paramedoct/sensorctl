# sensorctl

`sensorctl` is a lightweight time-series collector for Raspberry Pi Zero 2 W.
It schedules configured sensor drivers, accesses I2C, SPI, and UART devices,
and stores numeric measurements in SQLite.

The first release includes a BMP280 I2C driver, a deterministic mock driver,
and production transport adapters. Hardware-specific drivers are registered
in the static driver registry.

## Requirements

- Raspberry Pi OS Trixie, 32-bit or 64-bit
- Python 3.13 or newer

Install the required Debian packages:

```bash
./3rdparty/setup-debian.sh
```

## Install

```bash
sudo make
sudo editor /etc/sensors/sensors.toml
sudo sensorctl validate
sudo sensorctl enable
```

Installation does not enable or start the service. Once enabled, the service
starts automatically on every boot.

To remove the application and service while preserving configuration and data:

```bash
sudo make clean
```

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

## BMP280 over I2C

Connect the module to 3.3 V, ground, SDA, and SCL. Enable the Raspberry Pi I2C
interface, install `python3-smbus2`, and adapt
`config/bmp280.example.toml`. The driver accepts addresses `0x76` and `0x77`.
It records `temperature` in degrees Celsius and `pressure` in pascals.

The optional `temperature_oversampling` and `pressure_oversampling` values are
`1`, `2`, `4`, `8`, or `16`. Both default to `1`. Higher values reduce noise
but increase measurement time.

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
PYTHONPATH=src python3 -m unittest discover -s tests
ruff check .
ruff format --check .
mypy --strict .
make --dry-run
make --dry-run clean
```
