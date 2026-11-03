#!/bin/bash
# Run on the board as root (sudo). Installs Pyro4 offline and the QICK Pyro4 service.
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"

/usr/local/share/pynq-venv/bin/pip install --no-index "$HERE"/wheels/*.whl
cp "$HERE/qick-pyro.service" /etc/systemd/system/
systemctl daemon-reload
systemctl enable --now qick-pyro.service
sleep 20
systemctl --no-pager status qick-pyro.service | head -20
