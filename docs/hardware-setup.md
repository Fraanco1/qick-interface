# Hardware setup

How the board, the lab PC and the RF chain fit together, and how to install and repair the board service.

```
browsers on the lab network (CNEA Wi-Fi)
        │  http://192.168.1.111:8090
        ▼
Windows lab PC: QICK Analyzer, Wi-Fi 192.168.1.111 · Ethernet 192.168.1.2
        │  instruments' wired network (a switch; separate from the Wi-Fi)
        ├──▶ RFSoC 4x2 192.168.1.67: QICK Pyro4 service (:8888)
        ├──▶ LO: EXG N5173B 192.168.1.100 (SCPI :5025)
        └──▶ signal analyzer: PXA N9032B 169.254.136.224 (SCPI :5025)

RFSoC 4x2: DACs ──▶ mixers + LO ──▶ cryostat ──▶ mixer ──▶ ADCs
```

The two networks both use 192.168.1.x addresses but are separate, and Windows doesn't route between them. So a browser on the Wi-Fi reaches the board and the instruments only through the app.

## The board

| | |
|---|---|
| Board | Real Digital RFSoC 4x2, PYNQ image 2022_10_22, Python 3.10 |
| Address | `192.168.1.67` on the instruments' wired network (fixed, set by `board/eth0`), where the QICK service listens. The board's Ethernet goes to the instruments' switch. The micro-USB link still gives `192.168.3.1` to a PC plugged into it, for SSH and installing (`ssh xilinx@192.168.3.1`); it isn't needed to measure. |
| Lab PC | Windows 10 PC `DESKTOP-F8DQ84A`: wired `192.168.1.2` (instruments' network, with the board), Wi-Fi `192.168.1.111` (where browsers reach the page: `http://192.168.1.111:8090`). The app runs there with `--port 8090`, since National Instruments' web server holds 8080; the Windows firewall rule "QICK Analyzer 8090" lets the local network in. The two networks share the 192.168.1.x numbers but are separate: from Wi-Fi the board is reached only through this PC. |
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
- One LO serves both tones (upper sideband). For example, with the LO at 6.0 GHz: readout at about 7 GHz (IF ≈ 1.0 GHz, under the ADC's 2.21 GHz), qubit at about 10 GHz (IF ≈ 4.0 GHz, under the DAC's 4.9 GHz; the DAC's own roll-off costs about 2.4 dB there). The MMIQ accepts LO 4–16 GHz and IF up to 6 GHz.
- The mixer accepts LO 4–16 GHz at 7–16 dBm (13 dBm nominal) and IF from DC to 6 GHz. Datasheet notes: [mixer-mmiq-0416ls.md](research/mixer-mmiq-0416ls.md).
- Run the [I/Q calibration](user-guide.md#iq-calibration-iq-chips-only) after any change to the LO frequency or power.
- **Measured 2026-11-06** (MMIQ-0416LS, LO 5000 MHz at 13 dBm set by hand on the EXG, tone gain 0.5, RF to the PXA; scripts `C:\qick-setup\iq_char.py` and `iq_verify.py` on the lab PC, results in `iq_char.json`):
  - With the Q delay at 0 the sideband came out flipped at IF 1 GHz and with no suppression at IF 500 MHz: DAC_B (Q) ran **1500 ps** ahead of DAC_A on that boot. With 1500 ps the best Q phase is flat with IF (84–87° from 50 MHz to 3 GHz; fitted delay error −0.7 ps).
  - Optimised separately at each IF, the image is 61–70 dB down. The best Q/I gain is 0.98–1.01 up to 1 GHz and falls to 0.91 at 3 GHz.
  - One setting for all IFs (phase **85.7°**, Q/I gain **0.995**, delay 1500 ps; saved in the Transmon setup): image 43–46 dB below the wanted tone for IF 50–700 MHz, 33–39 dB for 1–3 GHz.
  - Wanted tone −12.5 dBm at IF 50 MHz to −16.8 dBm at 3 GHz (DAC roll-off); LO leakage about −56 dBm at every IF.
  - The Q delay changes at every power-up of the board (see [dac-tile-sync.md](research/dac-tile-sync.md)): measure it again after each one.
  - **Calibrate I/Q** (the app, same day, IF 50–3000 MHz every 250 MHz, 136 s): Q delay 1505.5 ps; image 66–74 dB below the tone at every table point, but only 34–49 dB between points (175, 640, 1111, 2222 MHz). A scan every 25 MHz (900–1400 MHz) shows why: the best Q phase and Q/I gain ripple with a **100 MHz period** (±1.5°, ±2.5 %), a reflection along about 1 m of cable (period = v / 2L, v ≈ 2.1·10⁸ m/s), most likely the DAC → mixer I/Q cables. A 250 MHz grid can't follow it. Either calibrate the band in use with a fine step (≤ 25 MHz; about 9 s per IF), or damp the ripple: 3–6 dB attenuators at the mixer's I and Q inputs (the reflection crosses them twice) and short, equal I/Q cables.
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

## Instruments on the wired network

The lab PC (Windows) reaches them over SCPI on port 5025:

| Instrument | Address | Notes |
|---|---|---|
| RFSoC 4x2 board | `192.168.1.67` | QICK Pyro4 service on port 8888 (not SCPI) |
| Lab PC (its Ethernet) | `192.168.1.2` | Runs the app; also `169.254.10.2` for the PXA (below) |
| Network analyzer: Keysight PNA-X | `192.168.1.6` | Plugged in only when needed (it was used to measure cables); not used by the app |
| LO: Keysight (Agilent) EXG N5173B, 9 kHz–20 GHz, −135 to +30 dBm (options 520, 1EA, 1E1) | `192.168.1.100` | |
| Signal analyzer: Keysight PXA N9032B | `169.254.136.224` | The app uses it with `--analyzer 169.254.136.224` (the Windows task does) for Setup → Board → **Calibrate DAC with analyzer**: a full-scale tone every 50 MHz from 50 to 4900 MHz, 1 MHz span, peak marker, plus the cable loss you type. During it the trace is set to clear/write (the PXA was found in Max Hold, which returned the same old peak every time) and put back afterwards; a peak marker outside the span stops the calibration. Measured 2026-11-06 with a 41 cm cable (0.15 dB): both DACs give −1.2 to −1.6 dBm below 1 GHz and fall to about −9 dBm at 4.9 GHz, much steeper than the data sheet; ADC_D and ADC_C (loopback from DAC_A) read full scale at +5.2 to +5.9 dBm, 2.5–3.5 dB above the data sheet. Its own automatic (link-local) address: its IP can't be changed without its administrator account. The lab PC has a second address on its Ethernet, `169.254.10.2/16`, and a route `169.254.136.224/32` through Ethernet; without the route Windows sends 169.254.x.x through Tailscale and gets no reply. It doesn't answer ping (its firewall); SCPI works. If the PXA ever shows another 169.254 address, replace the route: `New-NetRoute -DestinationPrefix <address>/32 -InterfaceAlias Ethernet -NextHop 0.0.0.0 -RouteMetric 0`. |

## The LO

The LO is a Keysight signal generator controlled over **LAN** with SCPI on port 5025: in the lab, the **EXG N5173B** at `192.168.1.100` (9 kHz to 20 GHz). A CXG N5166B (9 kHz to 6 GHz) works the same.

- Start the app with `--lo <address>`, e.g. `--lo 192.168.1.100` (the Windows task does).
- Before every run or output tone, the app sets the generator to the setup's **LO frequency** and **LO power**, turns modulation off (a pure CW tone) and RF on, waits for it to settle, and checks its error queue. RF stays on between runs. The status bar shows what it read back, e.g. "LO 6.000 000 GHz 14 dBm".
- The frequency and power range are the generator's own, read from it when it first answers. The LO power also stops at **+16 dBm**, the MMIQ-0416LS's limit (it wants 7–16 dBm, 13 nominal); the setup refuses more.
- An LO out of range, or a generator that does not answer, stops the run with a message.

Without `--lo` the LO is set by hand: type its frequency into the setup, and the app only uses it to convert between RF and IF.

## The board service

The app reaches QICK through a Pyro4 server on the board. `board/` in this repo holds:

| File | Role |
|---|---|
| `qick_service.py` | Starts the Pyro4 nameserver on 192.168.1.67:8888, waits until it answers, then loads the firmware and publishes the board as `rfsoc`. |
| `converters.py` | RF data converter settings QICK does not expose, published as `converters`: each DAC's coarse delay. (Setting it did not move the output on our firmware; kept for further tests.) |
| `scope.py` | The oscilloscope on the board's USB port (Tektronix MSO2024B), published next to the board as `scope` (`query`, `write`, `waveform`). Opened on first use; the service starts without it. |
| `qick-pyro.service` | systemd unit: starts at boot after the network is up; restarts on failure, at most 5 times in 5 minutes. |
| `eth0` | The board's Ethernet setup: fixed `192.168.1.67/24` (the wired network has no DHCP server), plus PYNQ's fallback `192.168.2.99`. |
| `install.sh` | Installs Pyro4 and the scope packages (pyusb, pyvisa, pyvisa-py) from local wheels and the Ethernet setup (keeping the original as `eth0.orig`), then installs and starts the unit. |

### Installing (or reinstalling)

From a PC plugged into the board's micro-USB port, from the repo:

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
- **DAC_B runs ahead of DAC_A** by a delay set at every power-up: 1.55 ns on one, 3.30 ns on the next; service restarts kept it. DAC_A and DAC_B are on different converter tiles, and the firmware has no multi-tile synchronization ([research](research/dac-tile-sync.md)). The setup's **Q delay** corrects it, in the carrier phase and in the pulse envelopes (whole cycles on the pulse start, the remaining fraction inside Gaussian envelopes); measure it after each power-up (user guide, "I/Q calibration"). With it, Q−I stays within ±0.6° from 20 to 150 MHz (was 111° to 266°). On the scope (`scripts/hardware_iq_envelopes.py`, Q delay 3.11 ns), the envelopes of a Gaussian and of a Gaussian-edges pulse go from Q 3.0–3.2 ns ahead to within 0.1 ns of I, on both edges.
- **Power scales** (`power.py`, user guide "Units"): the bench loopback DAC_B → ADC_D reads 2.4 dB (100 MHz) to 8 dB (2.1 GHz) less than the data sheets predict; with the DAC at its data-sheet value, ADC_D's full scale is +5.6 dBm at 150 MHz rising to +9.3 dBm at 1.95 GHz. The ~1 m loopback cable adds a ±0.7 dB ripple with a 100 MHz period (a standing wave between the ports); sweeps repeat to 0.001 dB.
- The scope handles one request at a time; a capture for the Q delay triggers on the mains (`LINE`), which always fires.

### The service owns the board

While the service runs, it holds the FPGA. Jupyter notebooks on the board must not load an overlay themselves; either connect through Pyro4 like the app does, or stop the service first.

### Security

QICK's Pyro4 server runs as root and accepts Python pickle, so anyone who can reach port 8888 can run code on the board. That is acceptable only because the instruments' wired network holds just the lab PC, the lab instruments and its gateway. **Never bridge it to the Wi-Fi or the institute network**; if other devices join it, add a firewall on the board that accepts only the lab PC. ([ADR 0001](adr/0001-web-app-on-lab-pc-pyro4-to-board.md))

### QICK versions

The PC compiles the QICK programs and the board runs them, so both must have the same QICK version (0.2.442). The app refuses to start on a mismatch. To upgrade, change both: the board's `~/jupyter_notebooks/qick` checkout, and the `qick==` pin in `pyproject.toml`.

## The app on the Windows lab PC

The app runs on the Windows PC, from `C:\Users\franco\qick-interface` (Python 3.12 virtual environment in `.venv`), as the scheduled task **QICK Analyzer**:

- It starts at boot, before anyone logs in, as the SYSTEM account, and runs `scripts\windows\run_server.cmd`.
- That script starts the app on port 8090 and starts it again 10 s after it stops, so a board that was off at boot is picked up once it is on.
- Output goes to `data\server.log`.

To install it (once, in an administrator PowerShell, from the repo):

```powershell
powershell -ExecutionPolicy Bypass -File scripts\windows\install_task.ps1
Start-ScheduledTask "QICK Analyzer"
```

Everyday commands (PowerShell, or over `ssh franco@192.168.1.111`):

```powershell
Get-ScheduledTask "QICK Analyzer"                 # Running?
Get-Content data\server.log -Tail 30              # its log
Stop-ScheduledTask "QICK Analyzer"; Start-ScheduledTask "QICK Analyzer"   # restart, e.g. after updating the code
```

Browsers reach it at `http://192.168.1.111:8090`. Machines that use the CNEA proxy must bypass it for `192.168.1.111` (the proxy answers 403); the [user guide](user-guide.md#opening-the-app) says how.

**Changing how it starts.** The options are in `scripts\windows\run_server.cmd`: `--port 8090 --lo 192.168.1.100 --analyzer 169.254.136.224`. Edit them there and restart the task. For example, while the EXG is off the network, remove `--lo 192.168.1.100` and set the LO by hand. Otherwise every run with an LO in its setup stops with "No answer from the LO at 192.168.1.100".

**Updating the code.** The lab PC has no GitHub access over SSH. Copy the commits over as a git bundle, then restart the task:

```bash
git bundle create update.bundle <last commit on the lab PC>..foundation          # on your PC
scp update.bundle franco@192.168.1.111:C:/Users/franco/update.bundle
ssh franco@192.168.1.111 "cd C:\Users\franco\qick-interface && git pull C:\Users\franco\update.bundle foundation"
```

**No remote access from outside the institute.** Tailscale is installed on the lab PC but logged out: the CNEA proxy refuses its servers (403 for `*.tailscale.com`, checked 2026-11-06). Remote access would have to come from the institute, e.g. its VPN. Never expose the app publicly: it has no passwords, and whoever reaches it controls the instruments.

## Troubleshooting

| Symptom | Cause and fix |
|---|---|
| App fails with `NamingError: unknown name: rfsoc` | The service is starting (loading the firmware takes about 15–30 s) or failing. Wait, then check `journalctl -u qick-pyro -n 50`. |
| App fails with `Failed to locate the nameserver` | The board is off, its Ethernet is unplugged, or the service is stopped. From the lab PC `ping 192.168.1.67`, then on the board `systemctl status qick-pyro`. |
| Service log: `nameserver could not start on 192.168.1.67:8888` | eth0 lacks that address (cable out, or `/etc/network/interfaces.d/eth0` changed) or the port is taken by an old process. Check `ip addr` on the board; restart the service. |
| Service is `failed` after 5 attempts | Read the log for the cause, fix it, then `reset-failed` and `start` (above). |
| `QICK version mismatch` | See [QICK versions](#qick-versions). |
| A notebook on the board broke when the app started | Both loaded the firmware; see [The service owns the board](#the-service-owns-the-board). |
| A browser shows **403 Forbidden** for `http://192.168.1.111:8090` | The CNEA proxy. Bypass it for `192.168.1.111` ([user guide](user-guide.md#opening-the-app)). |
| The page doesn't load at all | The lab PC is off or the app stopped: `Get-ScheduledTask "QICK Analyzer"` and `Get-Content data\server.log -Tail 30` on the lab PC. |
| Runs stop with "No answer from the LO at 192.168.1.100" | The EXG is off the network. Plug it back in, or start the app without `--lo` (see [The app on the Windows lab PC](#the-app-on-the-windows-lab-pc)). |
| curl or browsers can't reach `localhost:8080` on the lab PC | The lab's HTTP proxy intercepts it. Bypass the proxy for local addresses (e.g. `NO_PROXY=localhost`, or `curl --noproxy localhost`). |
