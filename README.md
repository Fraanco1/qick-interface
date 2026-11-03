# QICK Analyzer

A web instrument, in the style of a Keysight PNA-X, for measuring superconducting qubit chips with an RFSoC 4x2 board running [QICK](https://docs.qick.dev/latest/).

Anyone in the lab opens it in a browser. One person at a time controls the board; everyone else watches the same traces live.

It measures transmon and fluxonium chips:

- **Resonator sweep:** |S21| and phase of the readout resonator, with the cable delay removed.
- **Two-tone spectroscopy:** sweep a qubit tone while reading out at the resonator.
- **Rabi:** sweep the qubit pulse amplitude or length, with a fitted π-pulse.
- **I/Q calibration:** a continuous tone for nulling the image of an I/Q mixer on a spectrum analyzer.

Each chip keeps its own wiring (*setup profile*) and its own measured values (*chip parameters*), so each measurement starts from what the previous one found.

MKID arrays are read with Mazin Lab's MKIDGen3 instead; see [ADR 0004](docs/adr/0004-mkids-use-mkidgen3.md).

## Quick start

On the lab PC connected to the board (USB link, board at `192.168.3.1`):

```bash
python3 -m venv .venv
.venv/bin/pip install -e ".[dev]"
.venv/bin/python -m qick_interface          # real board
.venv/bin/python -m qick_interface --fake   # simulated chip, no hardware needed
```

Then open `http://<lab-PC-address>:8080` from any computer in the lab.

The board must be running the QICK Pyro4 service; see [hardware setup](docs/hardware-setup.md).

| Option | Default | Meaning |
|---|---|---|
| `--fake` | off | Simulate the board: a resonator, a qubit and Rabi oscillations |
| `--board` | `192.168.3.1` | Address of the board's Pyro4 nameserver |
| `--host` | `0.0.0.0` | Address the page is served on (`0.0.0.0` = all interfaces) |
| `--port` | `8080` | Port the page is served on |
| `--data` | `data` | Folder where runs are saved |
| `--profiles` | `profiles` | Folder with setup profiles and chip parameters |

## Documentation

| Document | Read it if you want to |
|---|---|
| [User guide](docs/user-guide.md) | measure a chip with the page |
| [Hardware setup](docs/hardware-setup.md) | wire the bench, install or repair the board service |
| [Developer guide](docs/developer-guide.md) | change the code or add a measurement |
| [Architecture](docs/architecture.md) | see how the modules fit together |
| [Glossary](GLOSSARY.md) | know exactly what a term means here |
| [Decision records](docs/adr/) | know why things are the way they are |
| [Research notes](docs/research/) | look up QICK, MKIDGen3 or mixer facts, with sources |
