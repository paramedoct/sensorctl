#!/usr/bin/env bash
set -euo pipefail

sudo apt update
sudo apt install \
  make \
  python3 \
  python3-alembic \
  python3-serial \
  python3-sqlalchemy \
  python3-setuptools \
  python3-smbus2 \
  python3-spidev \
  python3-venv
