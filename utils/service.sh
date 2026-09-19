#!/usr/bin/env bash

service_validate() {
  common_python validate --config "$SENSORS_CONFIG"
}

service_enable() {
  common_require_root
  service_validate
  systemctl enable --now sensors.service
}

service_disable() {
  common_require_root
  systemctl disable --now sensors.service
}

service_start() {
  common_require_root
  service_validate
  systemctl start sensors.service
}

service_stop() {
  common_require_root
  systemctl stop sensors.service
}

service_restart() {
  common_require_root
  service_validate
  systemctl restart sensors.service
}

service_status() {
  systemctl --no-pager --full status sensors.service || true
  common_python status --config "$SENSORS_CONFIG"
}
