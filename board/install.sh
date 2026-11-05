#!/bin/bash
# Installs Pyro4 and the oscilloscope packages (offline), the board's fixed Ethernet address (board/eth0) and the
# QICK Pyro4 service on the board. Run on the board with sudo.
#
# The board has no internet, so first download the wheels on the lab PC and copy this folder over:
#   python3 -m pip download --only-binary=:all: --python-version 3.10 --platform any -d board/wheels \
#       Pyro4 pyusb pyvisa pyvisa-py
#   ssh xilinx@192.168.3.1 mkdir -p qick-interface-board
#   scp -r board/* xilinx@192.168.3.1:qick-interface-board/
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

# the fixed Ethernet address the service listens on; the original file is kept once, next to this script
[ -e "$HERE/eth0.orig" ] || cp /etc/network/interfaces.d/eth0 "$HERE/eth0.orig"
install -m 644 "$HERE/eth0" /etc/network/interfaces.d/eth0
ifdown eth0:1 eth0 2>/dev/null || true
ifup eth0 eth0:1
ip -4 -br addr show eth0

sed "s|@DIR@|$HERE|" "$HERE/qick-pyro.service" > /etc/systemd/system/qick-pyro.service
systemctl daemon-reload
systemctl enable qick-pyro.service
systemctl restart qick-pyro.service
sleep 20
systemctl --no-pager status qick-pyro.service | head -20
