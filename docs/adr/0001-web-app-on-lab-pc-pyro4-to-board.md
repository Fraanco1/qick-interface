# Web app on the lab PC, board reached over Pyro4

The instrument is a web app served from the lab PC that is wired to the board, so anyone in the lab can open it by IP with no install. The PC runs the web server, measurement logic, fitting and the LO driver; the board only runs QICK's Pyro4 server (`board/qick_service.py`, started at boot). We chose this over running the web server on the board (its ARM CPU is slow for fitting/plotting, and the LO is attached to the PC) and over a desktop Qt app (only usable on one PC).

## Consequences

- The board is reachable from the instruments' wired network (192.168.1.67), which only the lab PC also joins from the Wi-Fi side, so the PC is the gateway for the lab. (Until November 2026 the board was on a USB link to a Linux lab PC, 192.168.3.1; the lab PC is now a Windows PC on the wired network.)
- The Pyro4 service owns the FPGA at boot: notebooks on the board must connect through Pyro4 instead of loading the firmware themselves, or stop `qick-pyro` first.
- PC and board must run the same QICK version (0.2.442), since programs are compiled on the PC.
- QICK's Pyro4 server runs as root and accepts pickle, so anyone who can reach 192.168.1.67:8888 can run code on the board. This is accepted because that wired network holds only the lab PC and lab instruments (signal analyzer, PNA-X, LO) and its gateway; it must not be bridged to the Wi-Fi or the institute network. If other devices join it, add a firewall on the board that accepts only the lab PC.
