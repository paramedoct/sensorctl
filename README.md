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
make
sudo editor /etc/sensorctl/sensorctl.toml
sudo sensorctl validate
sudo sensorctl enable
```

Installation does not enable or start the service. Once enabled, the service
starts automatically on every boot.

To remove the application and service while preserving configuration and data:

```bash
make clean
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

On shutdown, collection stops scheduling reads, waits for bus workers, closes
sample admission, and drains the database writer before recording final status.
The configured shutdown timeout covers worker and writer waits together.
If a thread is still running at the deadline, or a worker fails, collection
exits with an error instead of reporting a successful shutdown. In-flight
hardware operations cannot be forcibly interrupted; samples arriving after
admission closes are discarded.

The status JSON includes accepted and committed sample counts. Its `shutdown`
object records completion, remaining threads, errors, pending sensor tasks,
and samples not yet confirmed committed at shutdown assessment. That count
includes the writer's batch, not just the queue. After a timeout, an operation
may still finish before process exit, so these fields describe the shutdown
assessment rather than a definitive count of lost samples. If the status
writer is still running, the final file is not rewritten concurrently; consult
the service journal for the shutdown failure.

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
sudo cp /var/lib/sensorctl/sensorctl.db /path/to/export/
sudo sensorctl start
```

## Development

```bash
python3 -m pip install -e ".[dev]"
python3 -m unittest discover -s tests
ruff check .
ruff format --check .
mypy --strict .
python3 -m sensorctl --help
make --dry-run
make --dry-run clean
```
