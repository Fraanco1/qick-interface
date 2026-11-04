# User guide

How to measure a chip with QICK Analyzer. Words in *italics* are defined in the [glossary](../GLOSSARY.md).

## The page

Open `http://<lab-PC-address>:8080`.

- **Title bar:** the *chip* being measured, the *measurement*, who controls the board, your name, and **Take control**.
- **Screen:** two plot windows on a 10-division grid. The line above each window shows the trace, its scale per division and the reference value (at the ▶ arrow), like a PNA-X.
- **Soft keys** (right): menus with the measurement's settings, plus **Scale**, **Marker**, **Output**, **Setup** and, for chips with an I/Q output, **I/Q cal**. **Run sweep** and **Stop** are at the bottom.
- **Status bar:** what is on screen (measurement, start, stop, points, round), the board state (**Hold**, **Measuring** or **Tone**), and messages. Errors show in red.

On a phone the soft keys move under the screen.

## Controlling the board

Only one person, the *controller*, can change settings and start runs. Everyone else is a *viewer*: they see every run live, but the settings are greyed out.

1. Type your name in **Your name**, so others know who has the board.
2. Press **Take control**.

Taking control does not ask the current controller. Talk to them first: a run in progress keeps going, but the next one is yours.

## Setting up a chip

Each chip has a *setup profile*: how it is wired. Open **Setup**:

| Field | Meaning |
|---|---|
| Chip name | A name for this specific chip, e.g. "Transmon A". Letters, digits, spaces, `.`, `_` and `-`. |
| Chip type | Transmon or fluxonium. |
| LO frequency | The external LO, in MHz. Leave it empty when there is no mixer (RF = IF), for example a loopback test. |
| LO power | Set on the LO when the app controls it (started with `--lo`), in dBm. The MMIQ wants about 13–15 dBm. |
| Sideband | Upper: RF = LO + IF. Lower: RF = LO − IF. |
| Output path | Real: the tone leaves on one DAC. I/Q: the same tone on two DACs, 90° apart, into an I/Q mixer. |
| Readout output | The DAC used on the real path. |
| I output, Q output | The DACs used on the I/Q path (normally I = DAC_A, Q = DAC_B). |
| Electrical delay | Subtracted from the resonator sweep's phase, in ns. Empty: fitted on each sweep. Filled from a wide sweep (see [Resonator sweep](#1-resonator-sweep)). |
| Control line | None, or a DAC of its own for the qubit tone, with no mixer: the qubit frequency you type is the DAC frequency (up to 4915 MHz). Used by two-tone and Rabi. It can't be a DAC the readout output already uses. |
| Return path | Real: the signal comes back through a real mixer into one ADC. I/Q: through an I/Q mixer into two ADCs, combined in software, which rejects the image band (see [RX I/Q calibration](#rx-iq-calibration-iq-return-only)). |
| Readout input | The ADC that receives the signal (real return path). |
| I input, Q input | The ADCs for the mixer's I and Q outputs (normally ADC_D and ADC_C). Use cables of equal length. |
| RX Q / I gain, RX Q phase, RX I/Q delay | The RX I/Q calibration, filled in by that measurement. |

Press **Save setup**. To add a chip, change the name and save; the old chip stays.

The bottom of **Setup** lists the chip's *chip parameters*: values measured on it, filled in by the measurements below.

Setups and chip parameters are stored on the lab PC in `profiles/` (setups as `<chip>.json`, parameters in `profiles/parameters/<chip>.json`). They are not in git, so include that folder in the lab PC's backups.

The app checks every frequency against the setup before running. For example, it refuses an RF on the wrong side of the LO, or an IF above 2211.84 MHz for a tone the ADC must receive. The message says what to change.

## I/Q calibration (I/Q chips only)

An I/Q mixer also produces an *image* on the other side of the LO. With an uncalibrated MMIQ-0416LS it is only 25–30 dB weaker. Calibrating removes most of it.

1. Connect the mixer's RF output to a spectrum analyzer (or the PNA-X in spectrum mode).
2. Open **I/Q cal**, enter a **Frequency** inside the band you will measure (e.g. the readout frequency), and press **Tone on**.
3. On the analyzer, find the tone at RF and its image at LO − IF (upper sideband) or LO + IF (lower).
4. Adjust **Q phase offset** and **Q / I gain** until the image is smallest. Each change reaches the board immediately; arrow keys step by 0.1° and 0.005.
5. Press **Save setup**, then **Tone off**.

The status bar shows **Tone** while it plays. Starting a run turns the tone off.

The values are valid for one LO frequency and power; recalibrate when you change them.

## RX I/Q calibration (I/Q return only)

On the I/Q return path the app combines the I and Q readouts as Y_I + j·Y_Q. That rejects the image band only if the two paths are balanced; the mixer, the cables (about 48 ps, or 3.5° at 200 MHz IF, per cm of difference) and the ADC paths add a gain ratio, a phase offset and a delay. This measurement finds them, without a spectrum analyzer.

1. If the output is I/Q too, do the [I/Q calibration](#iq-calibration-iq-chips-only) of the output first: an image on the test tone would bias this one.
2. Measurement: **RX I/Q calibration**. Set **Start** and **Stop** to the band you will measure in, for example the readout frequency ± 50 MHz. The chip can stay connected: everything before the mixer cancels out.
3. **Run sweep**. Tr1 shows the Q/I gain and Tr2 the Q phase error against frequency, each with its fit (dashed). The screen shows the fitted **Q/I gain**, **Q phase**, **I/Q delay** and the expected **Image rejection** after correction; the scatter (noise) limits that estimate, so average more if it is low.
4. **Marker → Store RX calibration in setup**. Every measurement on this chip now uses it.

Recalibrate after changing the I/Q cables, or the LO frequency or power by much, or before measuring far from the calibrated band.

## Measuring a transmon: the usual order

### 1. Resonator sweep

Measurement: **Resonator sweep**.

| Menu | Settings |
|---|---|
| Sweep | Start, Stop (RF, MHz), Points |
| Power | Gain (0–1, fraction of full DAC scale) |
| Timing | Mode (Pulsed or CW), Settling time (CW), Pulse length (pulsed), Readout window, Time of flight, Repetition delay (pulsed) |
| Average | Averages per round, Rounds |

Press **Run sweep**. The traces update after every round; **Stop** ends the run after the current round.

**Pulsed or CW.**

- **Pulsed** (default): each shot sends one pulse, and the readout window opens one time of flight after the pulse starts.
- **CW** works like a PNA-X: the tone stays on and steps from frequency to frequency. At each point the app waits the **Settling time**, then measures over the readout window. Use CW for high-Q resonators, which don't reach steady state within a short pulse (loaded Q above about 10⁵ at 7 GHz). Make the settling time a few times the resonator's 1/κ: 1/κ ≈ 2.3 µs for κ/2π = 70 kHz.

On the bench loopback both modes give the same |S21| and phase (amplitude ratio 1.0000, phase within 0.4°). A longer readout window averages more noise away, like a lower IF bandwidth on the PNA-X.

- **Tr1:** |S21| in dB. It is relative, not calibrated: the received signal in ADC units divided by the gain, so it does not move when you change the gain (like a PNA-X). The resonance's frequency, width, depth and Q are what it measures well; the absolute level includes the whole chain.
  How it is computed, and what it can and can't be compared with: [How S21 is computed](s21.md).
- **Tr2:** phase in degrees, with the electrical delay removed (see below), wrapped to ±180°. With the lower sideband (RF below the LO) the mixer mirrors the phase; the app undoes that, so the resonance turns the same way on either sideband.

**Electrical delay.** The signal takes time τ to travel from the DAC to the ADC (cables, cryostat lines, and about 216 ns inside the board), which makes the phase fall by 360° every 1/τ of frequency, a steep ramp that hides the resonance. The app removes it by multiplying S21 by e^{+j2π·f·τ} (|S21| is unchanged) and centring the phase on 0°. Every sweep shows its own fitted delay on screen (**Electrical delay (ns)**). On a narrow sweep around a resonance that fit is tilted by the resonance's own phase turn, so:

1. Once per setup, run a **wide** sweep, for example a few hundred MHz, with points closer than 2 MHz apart, where the resonances are a small part of the data.
2. **Marker → Store in setup: electrical delay**.

From then on every resonator sweep of that chip subtracts the stored delay, so the resonance's phase keeps its true shape. Clear **Electrical delay** in **Setup** to go back to fitting each sweep. Measure it again after changing cables or the LO. The saved `s21` keeps the delay; only the phase trace is corrected.

Then **Marker → Min** puts the marker on the dip, and **Marker → Readout frequency** stores it in the chip parameters.

### CW Time: S21 against time

Measurement: **CW Time**. Like the PNA-X sweep type of the same name: the tone stays on at one frequency and the screen shows |S21| and phase against time. It sweeps again and again until you press **Stop**, redrawing the trace from the left each time. Use it to watch drifts, switching or anything else that changes in time at the resonator.

| Menu | Settings |
|---|---|
| Sweep | Frequency (RF, MHz; starts from the chip's readout frequency), Points |
| Power | Gain |
| Timing | Readout window, Settling time (after the tone starts, before the first point) |
| Average | Averages per point (back-to-back windows averaged into one point) |

- **Time per point** = readout window × averages per point (the window is rounded up to the board's 1.6 ns clock, so the windows never overlap); the x axis runs from 0 to (points − 1) × that, in µs, ms or s. The settling time counts from when the tone starts.
- **Noise:** the readout window plays the role of the PNA-X's IF bandwidth (IF BW ≈ 1 / window): 10 µs is like 100 kHz, 100 µs like 10 kHz. For less noise than a 100 µs window gives, raise **Averages per point**.
- Points within a sweep are exactly spaced by the board's clock. Between sweeps there is a short gap while the data travels to the PC, as on a PNA-X.
- The status bar counts **Sweep n**. When you press **Stop**, every sweep of the run is saved: `s21` has one row per sweep, and `sweep_end_unix_s` gives the time each sweep reached the PC. A long run uses about 16 bytes per point per sweep of memory on the lab PC until it is saved.

### 2. Two-tone spectroscopy

Measurement: **Two-tone spectroscopy**. **Readout → Readout frequency** is already filled in from step 1 ("From the chip parameters").

| Menu | Settings |
|---|---|
| Sweep | Qubit start, Qubit stop (RF, MHz), Points |
| Qubit | Qubit gain, Qubit pulse length |
| Readout | Readout frequency, gain, pulse length, window, time of flight |
| Average | Averages, Rounds, Repetition delay (default 50 µs, so the qubit relaxes between shots) |

The qubit tone may use an IF up to 4915.2 MHz, since only the DAC has to produce it. With the LO at 6.0 GHz (the CXG's maximum), a qubit near 10 GHz needs an IF of about 4.0 GHz, which the DAC and the MMIQ-0416LS accept. With a **Control line** in the setup (e.g. a fluxonium), the qubit tone goes out on that DAC instead, with no mixer, so the qubit frequencies you type are the DAC frequencies.

The qubit shows as a dip or peak in the readout signal. Put the marker on it and press **Marker → Qubit frequency**.

### 3. Rabi

Measurement: **Rabi**. Qubit and readout frequencies are filled in from steps 1 and 2.

- **Sweep = Amplitude:** a Gaussian pulse of width **Gaussian σ** (total length 4σ) whose gain goes from Start to Stop.
- **Sweep = Length:** a flat pulse of gain **Qubit gain** whose length goes from Start to Stop (µs).

**Tr1** is the readout signal along the direction it moves in the I/Q plane, with a damped-cosine fit as a dashed white line. **Tr2** is the phase.

When the fit explains the data, the screen shows the π-pulse (gain, or length in µs). For an amplitude sweep, **Marker → Store π-pulse gain** saves it. If there is no clear oscillation, no π-pulse is shown, rather than a meaningless number.

## Sending a tone (Output)

**Output** sends a tone on the selected chip's output path, like the CW source of a PNA-X, for checking cables, mixers and levels with an oscilloscope or spectrum analyzer. It works for every chip; on the I/Q path the tone goes out on both DACs with the saved I/Q calibration.

| Field | Meaning |
|---|---|
| Frequency | RF in MHz; the setup's LO and sideband give the board frequency. |
| Gain | 0–1, fraction of full DAC scale. |
| Mode | **Continuous**, or **Pulsed**: a pulse train with **Pulse length** and **Period** in µs. |

In pulsed mode, digital output **PMOD0_0** is high while each pulse plays (same start and length); connect it to the oscilloscope's trigger input. It is 1.8 V logic: trigger at about 0.9 V. The RF pulse may appear shifted from the marker by the DAC's latency (tens to a few hundred ns); compare both on the scope.

**Tone on** starts it; edits are applied immediately while it plays. The status bar shows **Tone** or **Pulses** and the frequency. **Tone off** or starting a run turns it off.

## Scale

**Scale** sets each trace window's y axis, like the PNA-X Scale key. It changes only your own screen; viewers set theirs.

| Field | Meaning |
|---|---|
| Autoscale | **On:** the axis follows the data on every update. **Off (fixed):** the axis stays where you put it, so traces from different runs line up. |
| Scale | Size of one division, e.g. 2 dB/div. |
| Reference level | The value on the reference line, marked ▶ on the left edge. |
| Reference position | Which division the reference line sits on: 0 = bottom, 10 = top, 5 = middle. |

Switching Autoscale off keeps the current view; **Autoscale once** fits the current data and stays fixed. The trace line above each window shows the scale, the reference value and **Fixed** when it is not autoscaling. Settings are kept in your browser, per measurement.

## Markers

- Click a trace to place the marker; the readout box shows its x value and both traces' values there.
- **Marker → Min / Max** jump to the extremes of Tr1. **Marker off** hides it.
- The **Marker** menu also has the measurement's "store" keys described above.

## Saved data

Every run is saved when it ends, including stopped runs, in `data/<date>/<time>_<measurement>_<chip>`:

- `.npz`: the arrays. `x`, every trace by name (e.g. `|S21| (dB)`, `Phase (°)`), and raw data such as the complex `s21`.
- `.json`: what produced them. Measurement, time, whether it completed, rounds done, the full setup profile, all parameters, the array names, and the QICK and app versions.

The status bar shows the file name after each run.

```python
import json
import numpy as np

name = "data/2026-11-03/174221_resonator_sweep_Transmon_A"
arrays = np.load(name + ".npz")
meta = json.load(open(name + ".json"))

freq_mhz = arrays["x"]
s21 = arrays["s21"]                     # complex: ADC units / gain, cable delay not removed
mag_db = arrays["|S21| (dB)"]
print(meta["params"], meta["profile"]["lo_mhz"])
```

## When something goes wrong

| Message or symptom | What to do |
|---|---|
| "Only the controller can …" | Press **Take control**. |
| "A run is already in progress." | Wait, or **Stop** it. |
| "With the upper sideband, RF must be above the LO …" | Move the sweep, the LO, or switch the sideband in **Setup**. |
| "IF up to … exceeds the readout limit of 2211.84 MHz" | Move the LO closer to the readout frequency. |
| "Connection to the instrument lost. Reconnecting…" | The app on the lab PC stopped; it reconnects by itself when it is back. |
| The app does not start: "unknown name: rfsoc" | The board service is not running; see [hardware setup](hardware-setup.md#troubleshooting). |
| The trace is flat at a low level | Check cables, the readout input, and that the LO is on. |
