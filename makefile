SHELL := /bin/bash
.SHELLFLAGS := -eu -o pipefail -c
.ONESHELL:
.DEFAULT_GOAL := all

ROOT_DIR := $(abspath $(dir $(lastword $(MAKEFILE_LIST))))
TARGET_DIR := /opt/sensorctl
CONFIG_DIR := /etc/sensorctl
CONFIG_FILE := $(CONFIG_DIR)/sensorctl.toml
STATE_DIR := /var/lib/sensorctl
SERVICE_FILE := /etc/systemd/system/sensorctl.service
# Remove the legacy variables and their usages after all installations migrate.
LEGACY_TARGET_DIR := /opt/sensors
LEGACY_CONFIG_DIR := /etc/sensors
LEGACY_CONFIG_FILE := $(LEGACY_CONFIG_DIR)/sensors.toml
MIGRATED_CONFIG_FILE := $(CONFIG_DIR)/sensors.toml
LEGACY_STATE_DIR := /var/lib/sensors
LEGACY_SERVICE_FILE := /etc/systemd/system/sensors.service
COMMAND_LINK := /usr/local/bin/sensorctl
LEGACY_LIB_DIR := /usr/local/lib/sensors

.PHONY: all clean migrate-legacy

all:
	@if [ "$$(id -u)" -ne 0 ]; then
	  exec sudo -- make --no-print-directory all
	fi
	if ! python3 -c 'import sys; raise SystemExit(sys.version_info < (3, 13))'; then
	  echo "Python 3.13 or newer is required" >&2
	  exit 1
	fi
	if ! python3 -m venv --help >/dev/null 2>&1; then
	  echo "python3-venv is required" >&2
	  exit 1
	fi
	if ! python3 -c 'import setuptools' >/dev/null 2>&1; then
	  echo "python3-setuptools is required" >&2
	  exit 1
	fi
	was_active=false
	if systemctl is-active --quiet sensorctl.service; then
	  was_active=true
	fi
	systemctl stop sensorctl.service 2>/dev/null || true
	make --no-print-directory migrate-legacy
	install -d -m 0755 "$(TARGET_DIR)" "$(CONFIG_DIR)"
	python3 -m venv --system-site-packages "$(TARGET_DIR)/venv"
	"$(TARGET_DIR)/venv/bin/pip" install \
	  --disable-pip-version-check --no-build-isolation --no-deps --no-index \
	  "$(ROOT_DIR)"
	ln -sfn "$(TARGET_DIR)/venv/bin/sensorctl" "$(COMMAND_LINK)"
	if [ ! -e "$(CONFIG_FILE)" ]; then
	  install -m 0644 "$(ROOT_DIR)/config/sensorctl.example.toml" \
	    "$(CONFIG_FILE)"
	fi
	install -m 0644 "$(ROOT_DIR)/systemd/sensorctl.service" "$(SERVICE_FILE)"
	systemctl daemon-reload
	rm -rf "$(LEGACY_TARGET_DIR)"
	if [ "$$was_active" = true ]; then
	  systemctl start sensorctl.service
	fi
	echo "installed; edit $(CONFIG_FILE) and run: sensorctl enable"

# Remove this target after all installations migrate.
migrate-legacy:
	@if [ "$$(id -u)" -ne 0 ]; then
	  echo "make migrate-legacy must run as root" >&2
	  exit 1
	fi
	systemctl disable --now sensors.service 2>/dev/null || true
	if [ -d "$(LEGACY_CONFIG_DIR)" ] && [ -e "$(CONFIG_DIR)" ]; then
	  echo "cannot migrate: both $(LEGACY_CONFIG_DIR) and $(CONFIG_DIR) exist" >&2
	  exit 1
	fi
	if [ -d "$(LEGACY_STATE_DIR)" ] && [ -e "$(STATE_DIR)" ]; then
	  echo "cannot migrate: both $(LEGACY_STATE_DIR) and $(STATE_DIR) exist" >&2
	  exit 1
	fi
	if { [ -e "$(LEGACY_CONFIG_FILE)" ] || \
	    [ -e "$(MIGRATED_CONFIG_FILE)" ]; } && [ -e "$(CONFIG_FILE)" ]; then
	  echo "cannot migrate: both configuration files exist" >&2
	  exit 1
	fi
	state_source="$(STATE_DIR)"
	if [ -d "$(LEGACY_STATE_DIR)" ]; then
	  state_source="$(LEGACY_STATE_DIR)"
	fi
	for suffix in '' -wal -shm; do
	  if [ -e "$$state_source/sensors.db$$suffix" ] && \
	      [ -e "$$state_source/sensorctl.db$$suffix" ]; then
	    echo "cannot migrate: both database files exist for suffix $$suffix" >&2
	    exit 1
	  fi
	done
	if [ -d "$(LEGACY_CONFIG_DIR)" ]; then
	  mv "$(LEGACY_CONFIG_DIR)" "$(CONFIG_DIR)"
	fi
	if [ -e "$(MIGRATED_CONFIG_FILE)" ]; then
	  mv "$(MIGRATED_CONFIG_FILE)" "$(CONFIG_FILE)"
	fi
	if [ -e "$(CONFIG_FILE)" ]; then
	  sed -i 's|/var/lib/sensors/sensors\.db|/var/lib/sensorctl/sensorctl.db|g' \
	    "$(CONFIG_FILE)"
	fi
	if [ -d "$(LEGACY_STATE_DIR)" ]; then
	  mv "$(LEGACY_STATE_DIR)" "$(STATE_DIR)"
	fi
	for suffix in '' -wal -shm; do
	  if [ -e "$(STATE_DIR)/sensors.db$$suffix" ]; then
	    mv "$(STATE_DIR)/sensors.db$$suffix" \
	      "$(STATE_DIR)/sensorctl.db$$suffix"
	  fi
	done
	rm -f "$(LEGACY_SERVICE_FILE)"
	rm -rf "$(LEGACY_LIB_DIR)"

clean:
	@if [ "$$(id -u)" -ne 0 ]; then
	  exec sudo -- make --no-print-directory clean
	fi
	systemctl disable --now sensorctl.service 2>/dev/null || true
	systemctl disable --now sensors.service 2>/dev/null || true
	rm -f "$(SERVICE_FILE)"
	rm -f "$(LEGACY_SERVICE_FILE)"
	rm -f "$(COMMAND_LINK)"
	rm -rf "$(TARGET_DIR)"
	rm -rf "$(LEGACY_TARGET_DIR)"
	rm -rf "$(LEGACY_LIB_DIR)"
	systemctl daemon-reload
	echo "removed application; /etc/sensorctl and /var/lib/sensorctl were preserved"
