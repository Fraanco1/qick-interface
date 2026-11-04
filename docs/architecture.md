# Architecture

How the app is split into modules. Vocabulary follows `GLOSSARY.md`; decisions behind it are in `docs/adr/`; QICK facts are in `docs/research/qick.md`.

## Layout

```
qick-interface/
├── board/                      # runs on the RFSoC: Pyro4 service (see ADR 0001)
├── src/qick_interface/
│   ├── board.py                # Board: the only code that talks to QICK
│   ├── frequency.py            # RF ↔ IF planning, image frequencies, limits
│   ├── profiles.py             # setup profiles and chip parameters, JSON per chip
│   ├── iq.py                   # tones on one DAC or an I/Q pair; readouts on one ADC or an I/Q pair
│   ├── tone.py                 # output tone: continuous or pulse train; also I/Q calibration
│   ├── measurements/
│   │   ├── base.py             # what a measurement produces (Update)
│   │   ├── resonator_sweep.py
│   │   ├── cw_time.py          # S21 against time at one frequency, until Stop
│   │   ├── two_tone.py
│   │   ├── rabi.py             # amplitude or length, damped-cosine fit
│   │   └── rx_iq_cal.py        # imbalance of the I/Q return path: gain, phase, delay
│   ├── session.py              # controller/viewers, one worker, live updates
│   ├── storage.py              # saves runs as .npz + .json
│   ├── server.py               # FastAPI: REST + WebSocket + static page
│   └── static/                 # index.html, app.js, style.css (no build step)
├── profiles/                   # setup profiles + chip parameters (local to the lab PC, not in git)
├── data/                       # saved runs (not in git)
└── tests/
```

## Modules

### Board (`board.py`)

The only module that touches hardware; Pyro4 never appears outside it.

- Interface: `soccfg`, and `run(program, rounds, should_stop, average=True)`, which yields the running average I/Q after each round; `average=False` yields each round on its own and keeps none in memory, and `rounds=None` repeats until stopped (CW Time).
- Hides: building the Pyro4 proxy without IPython, QICK version check (PC and board must match), `step_rounds` round-by-round acquisition, safe stop (`stop_tproc`, `stop_readout`, `reset_gens`), finite timeouts on every poll, board-side tracebacks.
- Interface also has `play(program)` / `silence()` for the I/Q calibration tone.
- Adapters: `QickBoard` (real board over Pyro4) and `FakeBoard` (computes a simulated response from the compiled program; used by tests and `--fake` mode).

Only one worker thread may use a Board: `QickSoc` has no locking and the Pyro4 server is multithreaded.

### Frequency planning (`frequency.py`)

Pure functions, no hardware. Given a setup profile and an RF range, returns the IF range and image range, or a readable error for an impossible request (RF on the wrong side of the LO; IF above the ADC's first Nyquist zone, 2211.84 MHz, or for drive-only tones the DAC's, 4915.2 MHz). QICK then rounds frequencies to its common generator/readout grid (≈ 20.6 Hz on the 4x2); measurements read the rounded values back from the program. This is where wiring mistakes are caught.

### Setup profiles and chip parameters (`profiles.py`)

One JSON file per chip in `profiles/`: chip name and type, LO frequency and sideband, output path (real / I/Q) with its DACs and I/Q calibration, readout ADC. The LO is a plain field until a real LO driver exists; the driver will be added here, not before. Not yet built: fluxonium control line, flux bias.

Chip parameters (readout and qubit frequency and gain, π-pulse gain and σ) live in `profiles/parameters/<chip>.json`, are filled from measurement results, and pre-fill measurement forms.

### Tones (`iq.py`)

Every program plays its tones and opens its readouts through `TonesMixin`. On the I/Q return path the I and Q readouts share one readout config and are triggered together, and `received_s21` combines them as Y_I + j·Y_Q after the RX calibration ([s21.md](s21.md)). For tones: on the real output path a tone is one pulse on one DAC; on the I/Q path it is the same pulse on the I and Q DACs with the profile's calibrated phase offset and gain ratio, both frequency-matched to the readout so they stay phase-locked.

### Measurements (`measurements/`)

Each measurement is one Python class that declares:

- parameters as a pydantic model with units, limits, soft-key group, and the chip parameter a field starts from (FastAPI exposes its JSON schema; the page builds the form from it),
- its x axis and plots (which traces share a plot, with units),
- the chip parameter its marker can be stored as, and which fit results can be stored (`marker_sets`, `info_sets`),
- `run(board, profile, params, should_stop)`, which yields `Update`s (x, traces, raw data to save, fit results).

Adding a measurement never requires web code. CW Time starts the tone once and triggers readout windows back to back at a fixed spacing; each round of its program is one sweep. The resonator sweep compiles one tProc program that sweeps generator and readout frequency together (dynamic readout, frequency-matched with `ro_ch`/`gen_ch`) and removes the fitted electrical delay from the phase.

### Session (`session.py`)

One worker thread owns the Board and runs one run at a time. Only the controller (identified by a per-browser token) can start or stop runs, play the calibration tone, or change profiles and chip parameters; viewers receive the same live updates. Control is taken explicitly. Starting a run silences the calibration tone. See ADR 0003.

### Storage (`storage.py`)

Each run is saved as `data/<YYYY-MM-DD>/<HHMMSS>_<measurement>_<chip>.npz` (arrays) plus a `.json` with the same name (parameters, setup profile, calibration, QICK and app versions).

### Server and page (`server.py`, `static/`)

Thin: routes, WebSocket fan-out, static files. No measurement logic.

## Testing

- `frequency.py`: plain unit tests, written first.
- Measurements: compile real QICK programs offline from a saved copy of the board's `soccfg`, run against `FakeBoard`.
- Server: FastAPI test client with `FakeBoard`.
- Hardware: a manual script that benchmarks a real sweep over Pyro4.
