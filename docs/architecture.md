# Architecture

How the app is split into modules. Vocabulary follows `GLOSSARY.md`; decisions behind it are in `docs/adr/`; QICK facts are in `docs/research/qick.md`.

## Layout

```
qick-interface/
├── board/                      # runs on the RFSoC: Pyro4 service (see ADR 0001)
├── src/qick_interface/
│   ├── board.py                # Board: the only code that talks to QICK
│   ├── frequency.py            # RF ↔ IF planning, image frequencies, limits
│   ├── profiles.py             # setup profiles, one JSON file per chip
│   ├── measurements/
│   │   ├── base.py             # what a measurement declares
│   │   └── resonator_sweep.py
│   ├── session.py              # controller/viewers, one worker, live updates
│   ├── storage.py              # saves runs as .npz + .json
│   ├── server.py               # FastAPI: REST + WebSocket + static page
│   └── static/                 # index.html, app.js, style.css (no build step)
├── profiles/                   # e.g. transmon-a.json
├── data/                       # saved runs
└── tests/
```

## Modules

### Board (`board.py`)

The only module that touches hardware; Pyro4 never appears outside it.

- Interface: `soccfg`, and `run(program, rounds, should_stop)`, which yields the running average I/Q after each round.
- Hides: building the Pyro4 proxy without IPython, QICK version check (PC and board must match), `step_rounds` round-by-round acquisition, safe stop (`stop_tproc`, `stop_readout`, `reset_gens`), finite timeouts on every poll, board-side tracebacks.
- Adapters: `QickBoard` (real board over Pyro4) and `FakeBoard` (simulated resonator, for tests and `--fake` mode).

Only one worker thread may use a Board: `QickSoc` has no locking and the Pyro4 server is multithreaded.

### Frequency planning (`frequency.py`)

Pure functions, no hardware. Given a setup profile and an RF range, returns the IF values, Nyquist zone, the generator/readout frequency grid (common step ≈ 20.6 Hz on the 4x2), image frequencies, and readable errors for impossible requests (e.g. IF above the ADC's first Nyquist zone, 2.21 GHz). This is where wiring mistakes are caught, so it carries the most tests.

### Setup profiles (`profiles.py`)

One JSON file per chip in `profiles/`: chip name and type, output path (real / I/Q), return path (real / I/Q), DAC and ADC ports, control line port (fluxonium), LO frequency and sideband, flux bias (manual value). The LO is a plain field until a real LO driver exists; the driver will be added here, not before.

### Measurements (`measurements/`)

Each measurement is one Python class that declares:

- parameters as a pydantic model with units and limits (FastAPI exposes its JSON schema; the page builds the form from it),
- its traces (e.g. `|S21| (dB)`, `phase (°)`),
- `run(board, profile, params)`, which yields updates.

Adding a measurement never requires web code. The resonator sweep compiles one tProc program that sweeps generator and readout frequency together (dynamic readout, frequency-matched with `ro_ch`/`gen_ch`) and removes the fitted electrical delay from the phase.

### Session (`session.py`)

One worker thread owns the Board and runs one run at a time. Only the controller (identified by a per-browser token) can start or stop runs; viewers receive the same live updates. Control is taken explicitly. See ADR 0003.

### Storage (`storage.py`)

Each run is saved as `data/<YYYY-MM-DD>/<HHMMSS>_<measurement>_<chip>.npz` (arrays) plus a `.json` with the same name (parameters, setup profile, calibration, QICK and app versions).

### Server and page (`server.py`, `static/`)

Thin: routes, WebSocket fan-out, static files. No measurement logic.

## Testing

- `frequency.py`: plain unit tests, written first.
- Measurements: compile real QICK programs offline from a saved copy of the board's `soccfg`, run against `FakeBoard`.
- Server: FastAPI test client with `FakeBoard`.
- Hardware: a manual script that benchmarks a real sweep over Pyro4.
