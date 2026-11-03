# User guide

How to measure a chip with QICK Analyzer. Words in *italics* are defined in the [glossary](../GLOSSARY.md).

## The page

Open `http://<lab-PC-address>:8080`.

- **Title bar:** the *chip* being measured, the *measurement*, who controls the board, your name, and **Take control**.
- **Screen:** two plot windows on a 10-division grid. The line above each window shows the trace, its scale per division and the reference (bottom) value, like a PNA-X.
- **Soft keys** (right): menus with the measurement's settings, plus **Marker**, **Setup** and, for chips with an I/Q output, **I/Q cal**. **Run sweep** and **Stop** are at the bottom.
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
| Sideband | Upper: RF = LO + IF. Lower: RF = LO − IF. |
| Output path | Real: the tone leaves on one DAC. I/Q: the same tone on two DACs, 90° apart, into an I/Q mixer. |
| Readout output | The DAC used on the real path. |
| I output, Q output | The DACs used on the I/Q path (normally I = DAC_A, Q = DAC_B). |
| Readout input | The ADC that receives the signal from the chip. |

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

## Measuring a transmon: the usual order

### 1. Resonator sweep

Measurement: **Resonator sweep**.

| Menu | Settings |
|---|---|
| Sweep | Start, Stop (RF, MHz), Points |
| Power | Gain (0–1, fraction of full DAC scale) |
| Timing | Pulse length, Readout window, Time of flight, Repetition delay |
| Average | Averages per round, Rounds |

Press **Run sweep**. The traces update after every round; **Stop** ends the run after the current round.

- **Tr1:** |S21| in dB, relative to the ADC's full scale (not calibrated to dBm).
- **Tr2:** phase in degrees, with the cable's electrical delay fitted and removed, wrapped to ±180°.

Then **Marker → Min** puts the marker on the dip, and **Marker → Readout frequency** stores it in the chip parameters.

### 2. Two-tone spectroscopy

Measurement: **Two-tone spectroscopy**. **Readout → Readout frequency** is already filled in from step 1 ("From the chip parameters").

| Menu | Settings |
|---|---|
| Sweep | Qubit start, Qubit stop (RF, MHz), Points |
| Qubit | Qubit gain, Qubit pulse length |
| Readout | Readout frequency, gain, pulse length, window, time of flight |
| Average | Averages, Rounds, Repetition delay (default 50 µs, so the qubit relaxes between shots) |

The qubit tone may use an IF up to 4915.2 MHz, since only the DAC has to produce it. With the LO at 6.8 GHz, a qubit near 10 GHz needs an IF of about 3.2 GHz, which the MMIQ-0416LS accepts.

The qubit shows as a dip or peak in the readout signal. Put the marker on it and press **Marker → Qubit frequency**.

### 3. Rabi

Measurement: **Rabi**. Qubit and readout frequencies are filled in from steps 1 and 2.

- **Sweep = Amplitude:** a Gaussian pulse of width **Gaussian σ** (total length 4σ) whose gain goes from Start to Stop.
- **Sweep = Length:** a flat pulse of gain **Qubit gain** whose length goes from Start to Stop (µs).

**Tr1** is the readout signal along the direction it moves in the I/Q plane, with a damped-cosine fit as a dashed white line. **Tr2** is the phase.

When the fit explains the data, the screen shows the π-pulse (gain, or length in µs). For an amplitude sweep, **Marker → Store π-pulse gain** saves it. If there is no clear oscillation, no π-pulse is shown, rather than a meaningless number.

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
s21 = arrays["s21"]                     # complex, in ADC units, cable delay not removed
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
