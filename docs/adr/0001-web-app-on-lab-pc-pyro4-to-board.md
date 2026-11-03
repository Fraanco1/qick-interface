# Web app on the lab PC, board reached over Pyro4

The instrument is a web app served from the lab PC that is wired to the board, so anyone in the lab can open it by IP with no install. The PC runs the web server, measurement logic, fitting and the LO driver; the board only runs QICK's Pyro4 server (`board/qick_service.py`, started at boot). We chose this over running the web server on the board (its ARM CPU is slow for fitting/plotting, and the LO is attached to the PC) and over a desktop Qt app (only usable on one PC).

## Consequences

- The board is reachable only from this PC (USB link, 192.168.3.x), so the PC is also the gateway for the lab.
- The Pyro4 service owns the FPGA at boot: notebooks on the board must connect through Pyro4 instead of loading the firmware themselves, or stop `qick-pyro` first.
- PC and board must run the same QICK version (0.2.442), since programs are compiled on the PC.
