# QICK Analyzer

A web instrument, in the style of a Keysight PNA-X, for measuring superconducting qubit chips with an RFSoC 4x2 board running [QICK](https://docs.qick.dev/latest/).

Anyone in the lab opens it in a browser. One person at a time controls the board; everyone else watches the same traces live.

It measures transmon and fluxonium chips:

- **Resonator sweep:** |S21| and phase of the readout resonator, pulsed or CW (tone always on, like a PNA-X), with the cable delay removed.
- **CW Time:** |S21| and phase against time at one frequency, redrawn sweep after sweep until Stop, like the PNA-X sweep type of the same name.
- **Oscilloscope:** a two-channel scope on the ADC inputs: raw voltage against time at 4.42 GS/s over 1.85 µs, one shot per redraw, while the readout pulse (optionally after a qubit pulse) plays.
- **Two-tone spectroscopy:** sweep a qubit tone while reading out at the resonator.
- **Rabi:** sweep the qubit pulse amplitude (Gaussian) or length (flat, or with Gaussian edges), with a fitted π-pulse.
- **I/Q return path:** an I/Q mixer into two ADCs, combined in software to reject the image band, with an automatic **RX I/Q calibration** (gain, phase, delay).
- **Scope sequences:** two-tone and Rabi play their own shot at one point, with an oscilloscope trigger, to check the pulses. A continuous tone for I/Q calibration.

Each chip keeps its own wiring (*setup profile*) and its own measured values (*chip parameters*), so each measurement starts from what the previous one found.

MKID arrays are read with Mazin Lab's MKIDGen3 instead; see [ADR 0004](docs/adr/0004-mkids-use-mkidgen3.md).

## Quick start

On the lab PC wired to the board (the Windows PC `192.168.1.111`/`192.168.1.2`; board at `192.168.1.67` on the instruments' wired network):

```bash
python3 -m venv .venv
.venv/bin/pip install -e ".[dev]"
.venv/bin/python -m qick_interface          # real board
.venv/bin/python -m qick_interface --fake   # simulated chip, no hardware needed
```

On Windows the same, with `py -3.12 -m venv .venv` and `.venv\Scripts\python.exe` in place of `.venv/bin/python`.

Then open `http://<lab-PC-address>:8080` from any computer in the lab.

The board must be running the QICK Pyro4 service; see [hardware setup](docs/hardware-setup.md).

| Option | Default | Meaning |
|---|---|---|
| `--fake` | off | Simulate the board: a resonator, a qubit and Rabi oscillations |
| `--board` | `192.168.1.67` | Address of the board's Pyro4 nameserver |
| `--host` | `0.0.0.0` | Address the page is served on (`0.0.0.0` = all interfaces) |
| `--port` | `8080` | Port the page is served on |
| `--data` | `data` | Folder where runs are saved |
| `--profiles` | `profiles` | Folder with setup profiles and chip parameters |
| `--analyzer` | none | IP address of the Keysight X-series signal analyzer (PXA N9032B); enables Setup → Board → Calibrate DAC with analyzer |
| `--lo` | none | IP address of the Keysight LO (EXG N5173B or CXG N5166B); the app then sets it from the setup before each run. Without it, the LO is set by hand |

## Documentation

| Document | Read it if you want to |
|---|---|
| [User guide](docs/user-guide.md) | measure a chip with the page (the page's **Help** key has the steps in short) |
| [How S21 is computed](docs/s21.md) | know what the traces mean, and how they compare with a PNA-X |
| [Hardware setup](docs/hardware-setup.md) | wire the bench, install or repair the board service |
| [Developer guide](docs/developer-guide.md) | change the code or add a measurement |
| [Architecture](docs/architecture.md) | see how the modules fit together |
| [Glossary](GLOSSARY.md) | know exactly what a term means here |
| [Decision records](docs/adr/) | know why things are the way they are |
| [Research notes](docs/research/) | look up QICK, MKIDGen3, mixer or pulse-shape facts, with sources |
