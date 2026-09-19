#!/usr/bin/env bash

service_validate() {
  common_python validate --config "$SENSORS_CONFIG"
}

service_apply() {
  common_require_root
  service_validate
  systemctl "$@" sensors.service
}

service_enable() {
  service_apply enable --now
}

service_disable() {
  common_require_root
  systemctl disable --now sensors.service
}

service_start() {
  service_apply start
}

service_stop() {
  common_require_root
  systemctl stop sensors.service
}

service_restart() {
  service_apply restart
}

service_status() {
  systemctl --no-pager --full status sensors.service || true
  common_python status --config "$SENSORS_CONFIG"
}
