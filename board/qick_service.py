#!/usr/bin/env python3
"""Runs on the RFSoC: starts a Pyro4 nameserver and exposes QickSoc to the lab PC.

Installed as a systemd service by board/install.sh. Must run as root inside the
PYNQ environment (`source /etc/profile`).
"""
import subprocess
import time

from qick.pyro import start_server

BITFILE = "/home/xilinx/jupyter_notebooks/qick_firmware/qick_4x2.bit"
HOST = "192.168.3.1"  # board address on the USB link to the lab PC
NS_PORT = 8888
PROXY_NAME = "rfsoc"

ns = subprocess.Popen(
    ["pyro4-ns", "-n", HOST, "-p", str(NS_PORT)],
    env={"PATH": "/usr/local/share/pynq-venv/bin:/usr/bin:/bin",
         "PYRO_SERIALIZERS_ACCEPTED": "pickle",
         "PYRO_PICKLE_PROTOCOL_VERSION": "4"},
)
time.sleep(5)  # let the nameserver come up

try:
    start_server(ns_host=HOST, ns_port=NS_PORT, proxy_name=PROXY_NAME, bitfile=BITFILE)
finally:
    ns.terminate()
