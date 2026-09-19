from __future__ import annotations

import os
import shutil
import subprocess

SERVICE_NAME = "sensors.service"


def _require_root() -> None:
    if os.geteuid() != 0:
        raise PermissionError("this command must run as root")


def _systemctl(*arguments: str) -> int:
    return subprocess.run(
        ["systemctl", *arguments, SERVICE_NAME], check=False
    ).returncode


def enable() -> int:
    _require_root()
    return _systemctl("enable", "--now")


def disable() -> int:
    _require_root()
    return _systemctl("disable", "--now")


def start() -> int:
    _require_root()
    return _systemctl("start")


def stop() -> int:
    _require_root()
    return _systemctl("stop")


def restart() -> int:
    _require_root()
    return _systemctl("restart")


def show_status() -> None:
    _systemctl("--no-pager", "--full", "status")


def show_journal() -> None:
    if shutil.which("journalctl") is None:
        return
    subprocess.run(
        ["journalctl", "--no-pager", "-u", SERVICE_NAME, "-n", "20"],
        check=False,
    )
