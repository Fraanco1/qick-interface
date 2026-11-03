#!/usr/bin/env python3
"""Runs on the RFSoC: starts a Pyro4 nameserver and exposes QickSoc to the lab PC.

Installed as a systemd service by board/install.sh. Must run as root inside the
PYNQ environment (`source /etc/profile`).
"""
import sys
import threading
import time

import Pyro4
from qick.pyro import start_nameserver, start_server

BITFILE = "/home/xilinx/jupyter_notebooks/qick_firmware/qick_4x2.bit"
HOST = "192.168.3.1"  # board address on the USB link to the lab PC
NS_PORT = 8888
PROXY_NAME = "rfsoc"

# start_nameserver makes Pyro4 in this process accept only pickle, so talk to it in pickle too
Pyro4.config.SERIALIZER = "pickle"
Pyro4.config.PICKLE_PROTOCOL_VERSION = 4
ns = threading.Thread(target=start_nameserver, args=(HOST, NS_PORT), daemon=True)
ns.start()
for _ in range(30):  # the USB link address may appear a little after boot
    if not ns.is_alive():
        sys.exit(f"Pyro4 nameserver could not start on {HOST}:{NS_PORT}; is the USB link up?")
    try:
        Pyro4.locateNS(host=HOST, port=NS_PORT)
        break
    except Pyro4.errors.NamingError:
        time.sleep(1)
else:
    sys.exit(f"Pyro4 nameserver did not answer on {HOST}:{NS_PORT} within 30 s.")

start_server(ns_host=HOST, ns_port=NS_PORT, proxy_name=PROXY_NAME, bitfile=BITFILE)
