SHELL := /bin/bash
.SHELLFLAGS := -eu -o pipefail -c
.ONESHELL:
.DEFAULT_GOAL := all

ROOT_DIR := $(abspath $(dir $(lastword $(MAKEFILE_LIST))))
TARGET_DIR := /opt/sensors
CONFIG_DIR := /etc/sensors
SERVICE_FILE := /etc/systemd/system/sensors.service
COMMAND_LINK := /usr/local/bin/sensorctl
LEGACY_LIB_DIR := /usr/local/lib/sensors

.PHONY: all clean

all:
	@if [ "$$(id -u)" -ne 0 ]; then
	  echo "make must run as root" >&2
	  exit 1
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
	install -d -m 0755 "$(TARGET_DIR)" "$(CONFIG_DIR)"
	python3 -m venv --system-site-packages "$(TARGET_DIR)/venv"
	"$(TARGET_DIR)/venv/bin/pip" install \
	  --disable-pip-version-check --no-build-isolation --no-deps --no-index \
	  "$(ROOT_DIR)"
	ln -sfn "$(TARGET_DIR)/venv/bin/sensorctl" "$(COMMAND_LINK)"
	if [ ! -e "$(CONFIG_DIR)/sensors.toml" ]; then
	  install -m 0644 "$(ROOT_DIR)/config/sensors.example.toml" \
	    "$(CONFIG_DIR)/sensors.toml"
	fi
	install -m 0644 "$(ROOT_DIR)/systemd/sensors.service" "$(SERVICE_FILE)"
	systemctl daemon-reload
	echo "installed; edit /etc/sensors/sensors.toml and run: sensorctl enable"

clean:
	@if [ "$$(id -u)" -ne 0 ]; then
	  echo "make clean must run as root" >&2
	  exit 1
	fi
	systemctl disable --now sensors.service 2>/dev/null || true
	rm -f "$(SERVICE_FILE)"
	rm -f "$(COMMAND_LINK)"
	rm -rf "$(TARGET_DIR)"
	rm -rf "$(LEGACY_LIB_DIR)"
	systemctl daemon-reload
	echo "removed application; /etc/sensors and /var/lib/sensors were preserved"
