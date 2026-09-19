#!/usr/bin/env bash

SENSORS_CONFIG=${SENSORS_CONFIG:-/etc/sensors/sensors.toml}
SENSORS_PYTHON=${SENSORS_PYTHON:-/opt/sensors/venv/bin/python}

common_require_root() {
  if [ "$(id -u)" -ne 0 ]; then
    echo "this command must run as root" >&2
    exit 1
  fi
}

common_python() {
  if [ -x "$SENSORS_PYTHON" ]; then
    "$SENSORS_PYTHON" -m sensors "$@"
    return
  fi
  PYTHONPATH="$ROOT_DIR/src${PYTHONPATH:+:$PYTHONPATH}" python3 -m sensors "$@"
}
