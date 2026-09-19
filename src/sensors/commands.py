from __future__ import annotations

import argparse
import json
import logging
import os
import shutil
import sys
from collections.abc import Sequence
from pathlib import Path

from sensors import control
from sensors.application import Collector
from sensors.config import AppConfig, ConfigError, load_config
from sensors.drivers.registry import DriverRegistry, PreparedDrivers

DEFAULT_CONFIG = Path(os.environ.get("SENSORS_CONFIG", "/etc/sensors/sensors.toml"))
DEFAULT_STATUS = Path("/run/sensors/status.json")


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="sensorctl")
    subparsers = parser.add_subparsers(dest="command", required=True)
    for name in (
        "collect",
        "validate",
        "enable",
        "start",
        "restart",
        "status",
        "diagnose",
    ):
        subparser = subparsers.add_parser(name)
        subparser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    subparsers.add_parser("disable")
    subparsers.add_parser("stop")
    subparsers.choices["collect"].add_argument(
        "--status-path", type=Path, default=DEFAULT_STATUS
    )
    subparsers.choices["status"].add_argument(
        "--status-path", type=Path, default=DEFAULT_STATUS
    )
    return parser


def _prepare_config(path: Path) -> tuple[AppConfig, PreparedDrivers]:
    config = load_config(path)
    return config, DriverRegistry().prepare(config)


def _validate(config_path: Path) -> int:
    config, _ = _prepare_config(config_path)
    print(
        f"configuration valid: {len(config.sensors)} sensors, {len(config.buses)} buses"
    )
    return 0


def _status(config_path: Path, status_path: Path) -> int:
    config, _ = _prepare_config(config_path)
    print(f"database: {config.database.path}")
    if config.database.path.exists():
        usage = shutil.disk_usage(config.database.path.parent)
        print(f"database_size_bytes: {config.database.path.stat().st_size}")
        print(f"disk_free_bytes: {usage.free}")
    else:
        print("database_size_bytes: 0")
        print("disk_free_bytes: unknown")
    try:
        payload = json.loads(status_path.read_text())
    except (OSError, json.JSONDecodeError):
        print("runtime: unavailable")
        return 0
    print("runtime: available")
    queue_status = payload.get("queue", {})
    print(
        f"queue: {queue_status.get('size', 'unknown')}/"
        f"{queue_status.get('capacity', 'unknown')}"
    )
    print(f"last_commit_ns: {payload.get('last_commit_ns')}")
    for sensor_id, status in sorted(payload.get("sensors", {}).items()):
        print(
            f"sensor {sensor_id}: reads={status.get('successful_reads', 0)} "
            f"failures={status.get('failed_reads', 0)} "
            f"missed={status.get('missed_deadlines', 0)} "
            f"dropped={status.get('dropped_samples', 0)} "
            f"error={status.get('last_error')}"
        )
    return 0


def _diagnose(config_path: Path) -> int:
    config, _ = _prepare_config(config_path)
    failed = False
    print(f"config: ok ({config_path})")
    print(f"python: {sys.version.split()[0]}")
    for bus in config.buses.values():
        if bus.type == "mock":
            print(f"bus {bus.id}: mock")
            continue
        device = bus.require_device()
        if device.exists():
            print(f"bus {bus.id}: ok ({device})")
        else:
            print(f"bus {bus.id}: missing ({device})")
            failed = True
    parent = config.database.path.parent
    target = parent if parent.exists() else parent.parent
    usage = shutil.disk_usage(target)
    print(f"disk_free_bytes: {usage.free}")
    return 1 if failed else 0


def main(argv: Sequence[str] | None = None) -> int:
    arguments = _parser().parse_args(argv)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    try:
        if arguments.command == "validate":
            return _validate(arguments.config)
        if arguments.command == "enable":
            _validate(arguments.config)
            return control.enable()
        if arguments.command == "start":
            _validate(arguments.config)
            return control.start()
        if arguments.command == "restart":
            _validate(arguments.config)
            return control.restart()
        if arguments.command == "disable":
            return control.disable()
        if arguments.command == "stop":
            return control.stop()
        if arguments.command == "status":
            control.show_status()
            return _status(arguments.config, arguments.status_path)
        if arguments.command == "diagnose":
            result = _diagnose(arguments.config)
            if result == 0:
                control.show_journal()
            return result
        config, prepared = _prepare_config(arguments.config)
        Collector(config, prepared, arguments.status_path).run()
        return 0
    except (ConfigError, OSError, RuntimeError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 1
