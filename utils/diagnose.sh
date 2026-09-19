#!/usr/bin/env bash

diagnose_run() {
  common_python diagnose --config "$SENSORS_CONFIG"
  if command -v journalctl >/dev/null 2>&1; then
    journalctl --no-pager -u sensors.service -n 20 || true
  fi
}
