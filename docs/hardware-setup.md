# Hardware setup

How the board, the lab PC and the RF chain fit together, and how to install and repair the board service.

```
lab PCs ──lab network──▶ lab PC: QICK Analyzer (:8080) ──USB link 192.168.3.x──▶ RFSoC 4x2: QICK Pyro4 service (:8888)
                                                                                    │
                                                         DACs ──▶ mixers + LO ──▶ cryostat ──▶ mixer ──▶ ADC
```

## The board

| | |
|---|---|
| Board | Real Digital RFSoC 4x2, PYNQ image 2022_10_22, Python 3.10 |
| Address | `192.168.3.1` on the USB link to the lab PC; `ssh xilinx@192.168.3.1` |
| QICK library | 0.2.442, in `~/jupyter_notebooks/qick` (must match the PC; see below) |
| Firmware | `~/jupyter_notebooks/qick_firmware/qick_4x2.bit` (custom build, 2025-12-09, tProc v2). **Not** the `qick_4x2.bit` bundled with the QICK library, which lacks the dynamic readouts the app needs. |
| Internet | None. Anything to install is downloaded on the PC and copied over. |

### Ports

The app names ports as they are labelled on the board.

| Port | QICK channel | Notes |
|---|---|---|
| DAC_A | generator 1 | 9830.4 Msps; tones up to 4915.2 MHz (first Nyquist zone) |
| DAC_B | generator 0 | 9830.4 Msps; tones up to 4915.2 MHz |
| ADC_D | readout 0 | 4423.68 Msps; signals up to 2211.84 MHz |
| ADC_C | readout 1 | same as ADC_D |
| ADC_B | readout 2 | same, but its buffer has a 4096-sample weights memory; windows longer than 7.4 µs are untested. Prefer ADC_D or ADC_C. |
| ADC_A | time tagger | not a readout; the app does not use it |
| PMOD0_0 | digital output, 1.8 V logic (LVCMOS18, FPGA pin AF16) | marker for the oscilloscope: high while each qubit pulse of an Output sequence (two-tone, Rabi) plays; during runs, a short pulse when each readout window opens. Which header pin it is has not been checked yet. |
| PMOD0_1–7 | digital outputs | not used yet |

DAC_A and DAC_B share a clock group, so the two outputs stay phase-locked, which the I/Q output path relies on. ADC_D, ADC_C and ADC_B are also clock-locked.

## Wiring per chip

### Transmon: I/Q output on one line

```
DAC_A (I) ─┐
           ├─▶ MMIQ-0416LS (LO in) ──RF──▶ cryostat input ··· chip ··· cryostat output ──▶ mixer (same LO) ──IF──▶ ADC_D
DAC_B (Q) ─┘
```

- Setup profile: output path **I/Q**, I = DAC_A, Q = DAC_B, readout input ADC_D.
- One LO serves both tones (upper sideband). The CXG reaches 6 GHz, so with the LO at 6.0 GHz: readout at about 7 GHz (IF ≈ 1.0 GHz, under the ADC's 2.21 GHz), qubit at about 10 GHz (IF ≈ 4.0 GHz, under the DAC's 4.9 GHz; the DAC's own roll-off costs about 2.4 dB there). The MMIQ accepts LO 4–16 GHz and IF up to 6 GHz.
- The mixer accepts LO 4–16 GHz at 7–16 dBm (13 dBm nominal) and IF from DC to 6 GHz. Datasheet notes: [mixer-mmiq-0416ls.md](research/mixer-mmiq-0416ls.md).
- Run the [I/Q calibration](user-guide.md#iq-calibration-iq-chips-only) after any change to the LO frequency or power.
- The return path is a real mixer into one ADC. An [I/Q return path](#iq-return-path) (two ADCs) is available; the board side is checked, but not yet with a real I/Q mixer.

### Fluxonium: real mixers, separate control line

```
DAC_B ──▶ real mixer (LO) ──▶ readout line ··· chip ··· ──▶ real mixer (same LO) ──▶ ADC_D
DAC_A ──────────────────────▶ control line (qubit tone, no mixer)
```

In the setup: output path **real**, readout output DAC_B, **Control line DAC_A**. Two-tone and Rabi then send the qubit tone on DAC_A at the frequency you type (no LO, up to 4915 MHz; the board's baluns attenuate below roughly 10–50 MHz), while the readout goes through the LO. The control line can't share a DAC with the readout output. The flux bias (a separate coil) is set by hand, outside the app.

### Bench loopback (no chip)

```
DAC_B ──cable──▶ ADC_D          DAC_A ──▶ oscilloscope
```

A setup profile with the **LO empty**, readout output DAC_B and readout input ADC_D measures the cable. This is the quickest check that the board and the app work:

```bash
.venv/bin/python scripts/hardware_sweep.py              # 100–1000 MHz, 1001 points
.venv/bin/python scripts/hardware_sweep.py 100 500 201  # start, stop (MHz), points
.venv/bin/python scripts/hardware_sweep.py ADC_C        # the loopback into another ADC
```

It prints |S21| and the phase spread per round, and the total time (about 0.34 s per round for 1001 points × 100 averages). It then checks CW Time: windows from 0.5 to 100 µs, the level against the sweep, noise against window length, phase between sweeps, and the real time per point.

On the bench loopback (2026-11-05, DAC_B → ADC_C): time of flight 0.295 µs at every frequency from 150 MHz to 2 GHz; electrical delay −116 ns in both pulsed and CW mode, whatever the time of flight; with ADC_C calibrated from the loopback, a sweep at gain 0.5 reads −7.15 dBm at 550 MHz (DAC_B data sheet: −7.0 dBm).

### I/Q return path

```
MMIQ I output ──cable A──▶ ADC_D        MMIQ Q output ──cable B──▶ ADC_C        (A and B phase-matched)
```

Cables of equal length matter: each centimetre of difference adds about 48 ps between I and Q, 3.5° at 200 MHz IF. The RX I/Q calibration removes what is left (see the user guide).

**Before relying on it**, check on the bench that the two readouts keep a fixed phase between runs:

```
DAC_A or DAC_B ──▶ power splitter ──▶ ADC_D
                                  └──▶ ADC_C
```

```bash
.venv/bin/python scripts/hardware_two_readouts.py               # 10 runs from DAC_B, 500–2000 MHz
.venv/bin/python scripts/hardware_two_readouts.py 10 DAC_A      # runs, DAC
```

The phase spread between runs must be well under 1°. The delay it prints is the difference between the two cables and board paths. The sweep stays inside 0.5–2 GHz: a splitter below its rated band adds its own imbalance.

**Measured 2026-11-05** (DAC_A → Mini-Circuits ZN2PD-183W-S+, 0.5–18 GHz → ADC_C and ADC_D):

| | Before a power-up | After a power-up |
|---|---|---|
| Phase C/D at 500 MHz | 1.10–1.16° | 1.05–1.13° |
| Spread between runs | 0.067° | 0.082° |
| Level ratio C/D | 0.9940 | 0.9943 |
| Delay between the paths | 8.1 ps | 7.9 ps |

The readouts are locked, and unlike the DACs (see "The oscilloscope" below) their relation does not change at power-up. So the RX I/Q calibration should stay valid across power-ups; confirm it once with the real mixer.

**The whole I/Q chain without mixers.** The I/Q output's two DACs cabled straight into the I/Q return's two ADCs act as an ideal I/Q mixer pair at the IF:

```
DAC_A (I) ──▶ ADC_D (I)        DAC_B (Q) ──▶ ADC_C (Q)        (equal cables, no LO)
```

```bash
.venv/bin/python scripts/hardware_iq_loop.py            # 5 calibration runs, then the image rejection
.venv/bin/python scripts/hardware_iq_loop.py 5 ADC_B    # another ADC for I
```

It runs the RX I/Q calibration several times over 100–1500 MHz, then applies it and measures the image rejection reached. **Measured 2026-11-05:**

| I input | Q/I gain | Q phase | I/Q delay | Image rejection (median, worst) |
|---|---|---|---|---|
| ADC_D | 0.991 | 178.40° | 3073 ps | 39–43 dB, 36 dB |
| ADC_B | 2.007 | 89.41° | 3067 ps | 38–45 dB, 33 dB |

- Every value repeats between runs (gain 0.0004, phase 0.001°, delay 0.6 ps).
- **ADC_D:** as expected. The gain is the ADCs' 0.994 times the two DACs' ratio. The phase is 180° because the DACs put Q 90° ahead of I, where the RX convention (a downconverting mixer, upper sideband) has it behind. The delay is the DAC tile skew of that power-up (Q ahead, about 3.07 ns, since the setup's Q delay was 0) plus the 8 ps between ADC_C and ADC_D.
- **ADC_B** reads about twice the scale of ADC_C and ADC_D and adds about 90°. Both are constant, so a calibration absorbs them, but use ADC_D and ADC_C as the I/Q pair. Its gain ratio (2.007) is also above the setup field's limit of 2, so it could not be stored from the page.
- **About 40 dB of image rejection**, limited by small differences between the two paths' frequency responses, which one gain, phase and delay can't follow. An uncalibrated MMIQ-0416LS gives 25–30 dB, so the board is not the limit.

## The LO

The LO is a Keysight **N5166B CXG** (option 506: 9 kHz to 6 GHz, up to about +18 dBm), controlled over **LAN** with SCPI on port 5025.

- Connect it to the lab PC's network and note its IP address (on the CXG: **Utility → I/O Config → LAN Setup**).
- Start the app with `--lo <address>`, e.g. `.venv/bin/python -m qick_interface --lo 192.168.1.50`.
- Before every run or output tone, the app sets the CXG to the setup's **LO frequency** and **LO power**, turns modulation off (a pure CW tone) and RF on, waits for it to settle, and checks its error queue. RF stays on between runs. The status bar shows what the CXG read back, e.g. "LO 6.000 000 GHz 14 dBm".
- An LO above 6 GHz, or a CXG that does not answer, stops the run with a message.
- The MMIQ-0416LS wants about 13–15 dBm of LO.

Without `--lo` the LO is set by hand: type its frequency into the setup, and the app only uses it to convert between RF and IF.

## The board service

The app reaches QICK through a Pyro4 server on the board. `board/` in this repo holds:

| File | Role |
|---|---|
| `qick_service.py` | Starts the Pyro4 nameserver on 192.168.3.1:8888, waits until it answers, then loads the firmware and publishes the board as `rfsoc`. |
| `converters.py` | RF data converter settings QICK does not expose, published as `converters`: each DAC's coarse delay. (Setting it did not move the output on our firmware; kept for further tests.) |
| `scope.py` | The oscilloscope on the board's USB port (Tektronix MSO2024B), published next to the board as `scope` (`query`, `write`, `waveform`). Opened on first use; the service starts without it. |
| `qick-pyro.service` | systemd unit: starts at boot after the network is up; restarts on failure, at most 5 times in 5 minutes. |
| `install.sh` | Installs Pyro4 and the scope packages (pyusb, pyvisa, pyvisa-py) from local wheels, installs and starts the unit. |

### Installing (or reinstalling)

On the lab PC, from the repo:

```bash
python3 -m pip download --only-binary=:all: --python-version 3.10 --platform any -d board/wheels Pyro4 pyusb pyvisa pyvisa-py
ssh xilinx@192.168.3.1 mkdir -p qick-interface-board
scp -r board/* xilinx@192.168.3.1:qick-interface-board/
```

Then, from a terminal where you can type the board's sudo password:

```bash
ssh -t xilinx@192.168.3.1 'sudo ~/qick-interface-board/install.sh'
```

The service runs `qick_service.py` from the folder you copied, so after editing only that file, copying it again is enough: the next restart uses it.

### Everyday commands (on the board)

```bash
systemctl status qick-pyro             # running?
journalctl -u qick-pyro -n 50          # its log
sudo systemctl restart qick-pyro       # reload the firmware and restart
sudo systemctl stop qick-pyro          # free the board, e.g. for Jupyter notebooks
sudo systemctl reset-failed qick-pyro && sudo systemctl start qick-pyro   # after 5 failed starts
```

### The oscilloscope

The bench scope (Tektronix MSO2024B, 200 MHz, 1 GS/s) is plugged into the board's USB port: CH1 on DAC_A, CH2 on PMOD0_0. The board's kernel has no USB instrument driver, so `scope.py` uses pyvisa-py over libusb, as root inside the service. `scripts/scope_check.py` uses it to check the qubit pulses (see the developer guide, "Tests").

Measured on the bench (2026-11-04):

- The qubit pulse on DAC_A starts **76 ns after** the PMOD0_0 rising edge (cables included); trigger on PMOD and expect that offset.
- PMOD0_0 swings 0 to 3.4 V. Into the scope's 1 MΩ input it rises in about 86 ns but falls in 8 ns and then rings for about 100 ns (down to −1.8 V, back up to +0.8 V): the line is unterminated. Measure its width between 50% points.
- Keep scope tones at 50–100 MHz to see the carrier; above about 150 MHz only the envelope is reliable.
- **DAC_B runs ahead of DAC_A** by a delay set at every power-up: 1.55 ns on one, 3.30 ns on the next; service restarts kept it. DAC_A and DAC_B are on different converter tiles, and the firmware has no multi-tile synchronization ([research](research/dac-tile-sync.md)). The setup's **Q delay** corrects it; measure it after each power-up (user guide, "I/Q calibration"). With it, Q−I stays within ±0.6° from 20 to 150 MHz (was 111° to 266°).
- **Power scales** (`power.py`, user guide "Units"): the bench loopback DAC_B → ADC_D reads 2.4 dB (100 MHz) to 8 dB (2.1 GHz) less than the data sheets predict; with the DAC at its data-sheet value, ADC_D's full scale is +5.6 dBm at 150 MHz rising to +9.3 dBm at 1.95 GHz. The ~1 m loopback cable adds a ±0.7 dB ripple with a 100 MHz period (a standing wave between the ports); sweeps repeat to 0.001 dB.
- The scope handles one request at a time; a capture for the Q delay triggers on the mains (`LINE`), which always fires.

### The service owns the board

While the service runs, it holds the FPGA. Jupyter notebooks on the board must not load an overlay themselves; either connect through Pyro4 like the app does, or stop the service first.

### Security

QICK's Pyro4 server runs as root and accepts Python pickle, so anyone who can reach port 8888 can run code on the board. That is acceptable only because the board sits on a point-to-point USB link to the lab PC. **Never bridge that link to the lab network.** ([ADR 0001](adr/0001-web-app-on-lab-pc-pyro4-to-board.md))

### QICK versions

The PC compiles the QICK programs and the board runs them, so both must have the same QICK version (0.2.442). The app refuses to start on a mismatch. To upgrade, change both: the board's `~/jupyter_notebooks/qick` checkout, and the `qick==` pin in `pyproject.toml`.

## Troubleshooting

| Symptom | Cause and fix |
|---|---|
| App fails with `NamingError: unknown name: rfsoc` | The service is starting (loading the firmware takes about 15–30 s) or failing. Wait, then check `journalctl -u qick-pyro -n 50`. |
| App fails with `Failed to locate the nameserver` | The board is off, the USB link is down, or the service is stopped. `ping 192.168.3.1`, then `systemctl status qick-pyro`. |
| Service log: `nameserver could not start on 192.168.3.1:8888` | The USB link address is missing (link down) or the port is taken by an old process. Check `ip addr` on the board; restart the service. |
| Service is `failed` after 5 attempts | Read the log for the cause, fix it, then `reset-failed` and `start` (above). |
| `QICK version mismatch` | See [QICK versions](#qick-versions). |
| A notebook on the board broke when the app started | Both loaded the firmware; see [The service owns the board](#the-service-owns-the-board). |
| curl or browsers can't reach `localhost:8080` on the lab PC | The lab's HTTP proxy intercepts it. Bypass the proxy for local addresses (e.g. `NO_PROXY=localhost`, or `curl --noproxy localhost`). |
