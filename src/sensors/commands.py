from __future__ import annotations

import argparse
import json
import logging
import shutil
import sys
from collections.abc import Sequence
from pathlib import Path

from sensors.application import Collector
from sensors.config import AppConfig, ConfigError, load_config
from sensors.drivers.registry import DriverRegistry

DEFAULT_CONFIG = Path("/etc/sensors/sensors.toml")
DEFAULT_STATUS = Path("/run/sensors/status.json")


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="sensors-collector")
    subparsers = parser.add_subparsers(dest="command", required=True)
    for name in ("collect", "validate", "status", "diagnose"):
        subparser = subparsers.add_parser(name)
        subparser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    subparsers.choices["collect"].add_argument(
        "--status-path", type=Path, default=DEFAULT_STATUS
    )
    subparsers.choices["status"].add_argument(
        "--status-path", type=Path, default=DEFAULT_STATUS
    )
    return parser


def _validated_config(path: Path) -> AppConfig:
    config = load_config(path)
    DriverRegistry().validate(config)
    return config


def _status(config_path: Path, status_path: Path) -> int:
    config = _validated_config(config_path)
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
    config = _validated_config(config_path)
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
            config = _validated_config(arguments.config)
            print(
                f"configuration valid: {len(config.sensors)} sensors, "
                f"{len(config.buses)} buses"
            )
            return 0
        if arguments.command == "status":
            return _status(arguments.config, arguments.status_path)
        if arguments.command == "diagnose":
            return _diagnose(arguments.config)
        config = _validated_config(arguments.config)
        Collector(config, arguments.status_path).run()
        return 0
    except (ConfigError, OSError, RuntimeError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 1
