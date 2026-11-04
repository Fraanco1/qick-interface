#!/usr/bin/env python3
"""Runs on the RFSoC: starts a Pyro4 nameserver and exposes QickSoc, the RF data converter settings and the oscilloscope to the lab PC.

Installed as a systemd service by board/install.sh. Must run as root inside the
PYNQ environment (`source /etc/profile`).
"""
import sys
import threading
import time

import Pyro4
from qick import QickSoc
from qick.pyro import start_nameserver

from converters import Converters  # board/converters.py, next to this file

BITFILE = "/home/xilinx/jupyter_notebooks/qick_firmware/qick_4x2.bit"
HOST = "192.168.3.1"  # board address on the USB link to the lab PC
NS_PORT = 8888
PROXY_NAME = "rfsoc"

# start_nameserver makes Pyro4 in this process accept only pickle, so talk to it in pickle too
Pyro4.config.SERIALIZER = "pickle"
Pyro4.config.PICKLE_PROTOCOL_VERSION = 4
ns_thread = threading.Thread(target=start_nameserver, args=(HOST, NS_PORT), daemon=True)
ns_thread.start()
for _ in range(30):  # the USB link address may appear a little after boot
    if not ns_thread.is_alive():
        sys.exit(f"Pyro4 nameserver could not start on {HOST}:{NS_PORT}; is the USB link up?")
    try:
        Pyro4.locateNS(host=HOST, port=NS_PORT)
        break
    except Pyro4.errors.NamingError:
        time.sleep(1)
else:
    sys.exit(f"Pyro4 nameserver did not answer on {HOST}:{NS_PORT} within 30 s.")


# What qick.pyro.start_server does, but keeping the QickSoc so the converters can be shared too
Pyro4.config.REQUIRE_EXPOSE = False  # QickSoc marks none of its methods; start_server sets this too
Pyro4.config.SERIALIZERS_ACCEPTED = {"pickle"}
ns = Pyro4.locateNS(host=HOST, port=NS_PORT)
daemon = Pyro4.Daemon(host=HOST)
soc = QickSoc(bitfile=BITFILE)
ns.register(PROXY_NAME, daemon.register(soc))
for obj in soc.autoproxy:  # objects reached through the QickSoc proxy (start_server does the same)
    daemon.register(obj)
ns.register("converters", daemon.register(Converters(soc)))
try:
    from scope import Scope  # board/scope.py; optional, skipped without its packages
    ns.register("scope", daemon.register(Scope()))
except ImportError as e:
    print(f"no oscilloscope support: {e}")
print("serving rfsoc, converters and scope")
daemon.requestLoop()
