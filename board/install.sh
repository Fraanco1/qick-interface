#!/bin/bash
# Installs Pyro4 (offline) and the QICK Pyro4 service on the board. Run on the board with sudo.
#
# The board has no internet, so first download the wheels on the lab PC and copy this folder over:
#   python3 -m pip download --only-binary=:all: --python-version 3.10 --platform any -d board/wheels Pyro4
#   scp -r board xilinx@192.168.3.1:qick-interface-board
#   ssh -t xilinx@192.168.3.1 'sudo ~/qick-interface-board/install.sh'
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"

shopt -s nullglob
wheels=("$HERE"/wheels/*.whl)
if [ ${#wheels[@]} -eq 0 ]; then
    echo "No wheels in $HERE/wheels; see the download step at the top of this script." >&2
    exit 1
fi
/usr/local/share/pynq-venv/bin/pip install --no-index "${wheels[@]}"

sed "s|@DIR@|$HERE|" "$HERE/qick-pyro.service" > /etc/systemd/system/qick-pyro.service
systemctl daemon-reload
systemctl enable qick-pyro.service
systemctl restart qick-pyro.service
sleep 20
systemctl --no-pager status qick-pyro.service | head -20
