# Developer guide

How to work on QICK Analyzer. Read [architecture.md](architecture.md) first for the module layout; this guide covers how to change it. Use the terms in the [glossary](../GLOSSARY.md), and check the [decision records](adr/) before reversing a design choice.

## Environment

```bash
python3 -m venv .venv
.venv/bin/pip install -e ".[dev]"
.venv/bin/pytest -q                          # all tests, about 1 s, no hardware
.venv/bin/python -m qick_interface --fake    # the full app on a simulated board, http://localhost:8080
```

Dependencies are in `pyproject.toml`. `qick` is pinned to the board's version (0.2.442); see [QICK versions](hardware-setup.md#qick-versions).

The page has no build step. `src/qick_interface/static/` is served as is, with uPlot 1.6.30 copied into `static/vendor/`, so the page works without internet.

## How the code fits together

```
browser ──REST──▶ server.py ──▶ session.py ──worker thread──▶ measurement.run(board, profile, params)
   ▲                                │                                 │
   └──────────── WebSocket ◀────────┘ broadcasts Updates              ├─ frequency.plan_sweep()  RF → IF, limits
                                                                      ├─ iq.TonesMixin           tones on 1 DAC or I/Q pair
                                                                      └─ board.run(program)      QickBoard | FakeBoard
```

- **`board.py`** is the only module that touches QICK hardware. `QickBoard` talks to the board over Pyro4; `FakeBoard` takes a function that computes a simulated response from the compiled program. Both expose `soccfg`, `run(program, rounds, should_stop, average=True)` (yields the running average per readout after each round; `average=False` yields each round alone, `rounds=None` runs until stopped), `play(program)` (start without waiting, e.g. the output tone) and `silence()`.
  - `QickBoard` runs its own round loop instead of QICK's `finish_round`: every wait on the board is finite (`poll_data(timeout=1.0)`), and a round with no new data for `STALL_S` (30 s) fails with a clear error. QICK's loop waits forever, and a board-side call left waiting steals data from later runs, so they hang too. Keep this when upgrading QICK.
- **`tone.py`** builds the continuous calibration tone used by I/Q calibration.
- **`power.py`** holds the board calibration (`profiles/board/calibration.json`; every `*.json` directly in `profiles/` is a chip): DAC output at gain 1 and ADC full scale, as tables against frequency, from the data sheets until measured. `calibrate_adc_from_loopback` derives an ADC's table from a dense loopback sweep, averaged over the cable's 100 MHz ripple. `drive_hints` turns a measurement's `drive_fields` (gain field → frequency field, line, shape; the shape may be a function of the other fields) into the dBm hints. The boards carry it as `board.calibration`; `measurements/base.py` converts with `received_dbm` and `received_mv`, and a plot declares its absolute version under `"absolute"`.
- **`iq_delay.py`** measures the Q delay for the I/Q cal tab's Measure key, with the oscilloscope: finds the I and Q channels (one DAC at a time), then fits the Q−I phase of an I/Q tone at 20–150 MHz to φ0 + 360°·f·τ. The correction itself is in `iq.py` (`_Output.lead_ps`): Q's phase is set 360°·f·τ earlier, also inside frequency sweeps. **`fake_scope.py`** stands in for the scope in `--fake` mode and tests; it shows what the `FakeBoard` plays, each DAC on a channel with its own lead.
- **`time_of_flight.py`** measures the time of flight for the Setup panel's Measure key: a 5 µs window opens with a 1 µs test pulse (off the resonator), `board.capture()` returns the averaged samples, and the arrival is where the amplitude reaches half the pulse's level.
- **`frequency.py`** is pure: RF ↔ IF for a setup profile, and the ADC/DAC limits.
- **`iq.py`** makes every program play its tones the same way: one pulse on one DAC (real path), or the same pulse on the I and Q DACs with the calibrated phase and gain (I/Q path).
- **`measurements/`**: one class per measurement (below).
- **`session.py`** owns the single worker thread, the controller, the calibration tone, and the broadcast to viewers ([ADR 0003](adr/0003-single-controller.md)).
- **`server.py`** is thin: routes and the WebSocket. It serves the page with `Cache-Control: no-cache`, so browsers pick up a new version as soon as the app restarts. **`storage.py`** saves runs. **`profiles.py`** stores setup profiles and chip parameters.

## Adding a measurement

A measurement is one Python file; the page builds its form and plots from what the class declares, so no web code is needed ([ADR 0002](adr/0002-hand-written-page-measurements-in-python.md)). [`two_tone.py`](../src/qick_interface/measurements/two_tone.py) is a good model to copy.

### 1. Parameters

A pydantic model. Each field's `json_schema_extra` tells the page how to show it:

| Key | Effect |
|---|---|
| `group` | The soft-key menu the field appears in (e.g. "Sweep", "Readout"). |
| `unit` | Shown next to the input. |
| `from_chip` | The chip parameter that pre-fills the field (e.g. `"readout_freq_mhz"`). |
| `shown_when` | Show the field only while other fields have these values, e.g. `{"mode": "pulsed"}`; a list allows several, e.g. `{"qubit_pulse": ["flat", "gaussian"]}`. |

Use `title` for the label and `description` for a hint under the field. `ge`/`le`/`gt` limits are checked by the server, and a violation comes back to the page as a readable error. A `Literal[...]` field becomes a drop-down. `two_tone.py` and `rabi.py` define a small `_f()` helper that builds these fields.

### 2. The QICK program

Subclass `TonesMixin` and `AveragerProgramV2`. Put the profile's outputs in `cfg["outputs"]` (from `iq.outputs()`) and its inputs in `cfg["inputs"]` (from `iq.inputs()`: one readout, or I and Q on the I/Q return path), then:

```python
class _Program(TonesMixin, AveragerProgramV2):
    def _initialize(self, cfg):
        self.declare_outputs(cfg)
        self.declare_inputs(cfg, length=cfg["readout_length"])
        self.add_readout(cfg, "ro", freq=cfg["readout_freq"])
        self.add_loop("sweep", cfg["points"])
        self.add_tone(cfg, "qubit", freq=cfg["qubit_freq"], gain=cfg["swept"], length=cfg["qubit_length"])
        self.add_tone(cfg, "readout", freq=cfg["readout_freq"], gain=cfg["readout_gain"], length=cfg["readout_pulse"])

    def _body(self, cfg):
        send_readouts(self, cfg, "ro")
        self.play_tone(cfg, "qubit", t=0)
        self.delay_auto(t=0.05)
        self.play_tone(cfg, "readout", t=0)
        self.read(cfg, pins=[0], t=cfg["trigger_delay"])  # profile.time_of_flight_us
```

A qubit tone goes on the chip's control line when the setup has one: put `control_outputs()` in `cfg["control"]`, pass `line="control"` to `add_tone` (and `add_gauss_envelope`), and plan its frequency with `plan_drive()` (x axis: `drive_rf_from_if()`). `play_tone` remembers each tone's line.

Always go through these helpers (`declare_inputs`, `add_readout`, `send_readouts`, `read`) rather than QICK's readout calls, so every measurement works on both return paths.

Rules that keep data correct (details and sources in [research/qick.md](research/qick.md)):

- **Sweep inside the tProc** with `QickSweep1D`, not with a Python loop: one program per run is fast, and per-point programs run out of waveform memory.
- **Frequency matching:** `add_tone` passes `ro_ch`, and `add_readoutconfig` must get `gen_ch`. Without both, the phase changes from run to run.
- **Plan frequencies first:** convert RF to IF with `plan_sweep(profile, start, stop)`. Pass `drive_only=True` for tones the ADC never receives (e.g. a qubit tone).
- **Read axes back from QICK:** use `program.get_pulse_param(name, param, as_array=True)`, which returns the values QICK rounded to, instead of recomputing them.
- **Gain** is a fraction of full scale (0–1), times are in µs, and frequencies in MHz.
- **Turn the readouts' I/Q into S21 with `received_s21(iq, program, tone, profile)`** (`measurements/base.py`), passing the whole list `iq` from `board.run`: it combines the I and Q readouts on the I/Q return path (with the RX calibration), conjugates on the lower sideband where needed, and divides by the readout tone's gain. See [s21.md](s21.md).

### 3. The class

```python
class MyMeasurement:
    name = "My measurement"                          # shown in the Measurement menu
    Params = MyParams
    x_axis = {"title": "Qubit frequency", "unit": "MHz"}   # "MHz" gets GHz/MHz formatting
    plots = [{"title": "S21 LogMag", "unit": "dB", "traces": ["|S21| (dB)"]},
             {"title": "S21 Phase", "unit": "°", "traces": ["Phase (°)"]}]   # exactly two windows
    marker_sets = "qubit_freq_mhz"                   # what "Marker → …" stores, or None
    info_sets = {}                                   # fit result name → chip parameter
    run_key = "Run sweep"                            # optional: the run key's label (default)
    # optional, per window: "views" lists other plots to show there (Scale → Show, per browser), the first being
    # the default, e.g. Rabi's raw I, Q, |S21|. A view with "iq": True draws traces [I, Q, fit I, fit Q] as Q
    # against I. Each view, like each plot, may carry its "absolute" version.
    setup_requires = {}                              # optional: e.g. {"return_path": "iq"}; else not listed

    @classmethod
    def run(cls, board, profile, params, should_stop=lambda: False):
        ...  # plan frequencies, build the program, then:
        for i, iq in enumerate(board.run(program, params.rounds, should_stop), start=1):
            yield Update(i, params.rounds, x, traces={...}, raw={"s21": iq[0]}, info={...})
```

A pulsed measurement can also offer a **scope sequence** (see `rabi.py`, `two_tone.py`): put the one point it plays in parameters of the group `"Output"`, and add a classmethod `sequence(soccfg, profile, params)` that returns the same program with that point fixed, both loops at `tone.LOOP_MAX` (it plays until silenced), and a PMOD0_0 trigger on the qubit pulse. The page then shows Play sequence and Off in the Output menu. Parameters only a run needs can be skipped for the sequence: it validates with `context={"sequence": True}` (see `TwoToneParams`).

A measurement that runs until Stop (like `cw_time.py`) passes `rounds=None` to `board.run` and to its `Update`s; the page then shows "Sweep n", and Stop counts as a completed run.

`Update` (in `measurements/base.py`) carries:
- `x` and `traces`: what is plotted. A second trace in a plot is drawn as a dashed fit line.
- `raw`: extra arrays that are saved but not plotted.
- `x_axis`: overrides the class default, e.g. when a parameter changes the axis.
- `info`: fit results, shown on the screen and storable via `info_sets`.

Non-finite values (NaN, ±inf) are sent to the page as gaps.

### 4. Register, simulate, test

1. Add it to `MEASUREMENTS` in `server.py`.
2. Teach `simulated_chip()` in `__main__.py` to answer for it, so `--fake` shows something sensible.
3. Write tests (next section), then run it on the bench loopback.
4. If it needs new chip parameters, add them to `ChipParameters` in `profiles.py` and to `PARAMETER_LABELS` in `static/app.js`.

## Tests

Tests are written first (red, then green) and only at four agreed places:

| Where | File | Catches | Misses |
|---|---|---|---|
| Frequency planning | `tests/test_frequency.py` | wiring and sideband mistakes, out-of-range IFs | QICK's frequency rounding |
| Measurements on `FakeBoard` | `tests/test_resonator_sweep.py`, `test_cw_time.py`, `test_two_tone.py`, `test_rabi.py`, `test_iq_return.py`, `test_iq_output.py`, `test_iq_delay.py`, `test_power.py`, `test_time_of_flight.py`, `test_oscilloscope.py` | the program compiles for this firmware, axes, processing, fits | real timing, Pyro4 |
| Server | `tests/test_server.py` (with `tests/fake_cxg.py`, a stand-in CXG on localhost) | controller rules, schemas, live updates, saving, tone | how the page looks |
| Real board | `scripts/hardware_sweep.py`, `scripts/hardware_two_readouts.py`, `scripts/scope_check.py`, `scripts/hardware_iq_loop.py`, `scripts/hardware_iq_envelopes.py` (manual) | the whole chain on hardware; `scope_check.py [channel of DAC_A]` measures on the oscilloscope the qubit pulses on a control line and, transmon-like, the qubit pulse, delay and readout pulse on one DAC (lengths, carriers, gain, Gaussian width, Gaussian edges, readout timing, PMOD marker, shot period; about 1 min) | — |

- **Firmware fixture.** Measurement tests compile real QICK programs against `tests/fixtures/soccfg_rfsoc4x2.json`, a copy of the board's firmware configuration. After changing the firmware, refresh it:

  ```python
  import Pyro4; from qick import QickConfig
  Pyro4.config.SERIALIZER = "pickle"
  soc = Pyro4.Proxy(Pyro4.locateNS(host="192.168.3.1", port=8888).lookup("rfsoc"))
  open("tests/fixtures/soccfg_rfsoc4x2.json", "w").write(QickConfig(soc.get_cfg()).dump_cfg())
  ```

- **Assert on outcomes,** such as "the dip is at 10.05 GHz" or "the fit finds π at gain 0.4", not on internals. A test may read a compiled program's pulse settings (`get_pulse_param`), because that is QICK's public view of what will be played.
- **The page** has no automated tests. Check it in `--fake` mode in a browser, at desktop and phone widths.

## The page (`static/`)

`app.js` is organised in sections: server calls, formatting, soft-key menus, setup profiles and I/Q calibration, control, plots, live connection, start-up. It keeps three kinds of state:

- **From the server:** the measurements and their schemas, setup profiles, chip parameters, controller and running state, the calibration tone, the last update.
- **Per browser** (`localStorage`, always optional): the client id, your name, the open menu, and typed parameter values per measurement and chip (`qi.params.<measurement>.<chip>`).
- **On screen:** the plots and the marker.

A field's value is what the user typed, else the chip parameter it starts from, else its default. Storing a new chip parameter clears what was typed into the fields that start from it.

Style tokens (colors, font) are CSS variables at the top of `style.css`.

The **Help** panel is static text in `index.html` (the steps to measure, one line per measurement). When a measurement, mode or key is added or renamed, update it there too, and keep it short: it links to `docs/user-guide.md` on GitHub (`main`) for detail.

## REST and WebSocket interface

Requests that change anything carry `X-Client-Id` (a random id per browser) and are refused with 403 unless the client is the controller. `X-Client-Name` is URL-encoded.

| Method and path | Purpose |
|---|---|
| `GET /api/measurements` | Measurements with parameter schemas, x axis, plots, `marker_sets`, `info_sets`, `sequence`, `run_key`, `setup_requires` |
| `GET /api/profiles` · `PUT /api/profiles/{chip}` · `DELETE /api/profiles/{chip}` | List, create or replace, or delete setup profiles (changes: controller only). Delete also removes the chip parameters; runs stay. |
| `GET /api/parameters/{chip}` · `PATCH /api/parameters/{chip}` | Read, add or overwrite chip parameters (controller only) |
| `POST /api/control` | Become the controller |
| `POST /api/runs` · `POST /api/runs/stop` | Start a run `{measurement, chip, params}` (409 if busy, 422 if invalid); stop after the current round |
| `POST /api/tone` · `POST /api/tone/off` | Play the I/Q calibration tone `{chip, rf_mhz, gain, iq_phase_deg?, iq_gain_ratio?}`, or stop whatever plays (tone or sequence) |
| `GET /api/board` · `PUT /api/board` | Read or replace the board calibration (controller only for changes) |
| `POST /api/board/adc-from-loopback` | `{dac, adc}`: calibrate the ADC from a loopback cable, keep it in `profiles/board/calibration.json` → the new calibration. Controller only |
| `POST /api/drive-power` | `{measurement, chip, params}` → `{field: "≈ −7.0 dBm at DAC_B (data sheet)"}` for the gain fields |
| `POST /api/iq-delay` | Measure the Q delay of a setup profile with the oscilloscope → `{iq_delay_ps, i_channel, q_channel, phase_at_0_deg}`. Controller only; 503 without a scope |
| `POST /api/time-of-flight` | Measure the time of flight of a setup profile (the body; it need not be saved yet) → `{time_of_flight_us}`. Controller only |
| `POST /api/sequence` | Play a pulsed measurement's shot at one point until `/api/tone/off` `{measurement, chip, params}` |
| `WS /ws` | Live messages; on connect, the current state and the last update |

WebSocket messages have a `type`:
- `state`: controller, controller name, running, tone.
- `update`: measurement, chip, round, rounds, x, traces, x axis, info.
- `parameters`: a chip's parameters changed.
- `saved`: the file name.
- `error`: a message.

## Board-side code

`board/` runs on the RFSoC as a systemd service; see [hardware setup](hardware-setup.md#the-board-service). Changes there need copying to the board, and the unit file needs `install.sh` (sudo). Pyro4's configuration is global per process: once the nameserver is started, everything in that process must use the pickle serializer.

## Conventions

- **Simplicity:** the simplest code that solves today's problem. No configuration or abstraction without a second user (e.g. one concrete LO driver, `CxgLo`, with no LO base class until a second LO model exists).
- **Vocabulary:** names follow the [glossary](../GLOSSARY.md). Update it when a term is settled.
- **Decision records:** record hard-to-reverse, non-obvious decisions as a short [ADR](adr/).
- **Code review:** review before merging, and verify on the bench loopback what can be verified there.

## Not built yet

- Flux bias from the app (it is set by hand on its own coil).
- Testing the LO driver against the real CXG (it is tested against `tests/fake_cxg.py`).
- Viewers see the controller's frequency range only in the status bar, not in the form fields.
