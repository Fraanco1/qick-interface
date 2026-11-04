# qick-interface

A lab instrument, in the style of a vector network analyzer, for measuring superconducting qubit chips with an RFSoC board, an external LO and mixers.

## Hardware

**Board**:
The RFSoC 4x2 that generates and digitizes the tones, running one firmware at a time.
_Avoid_: FPGA, RFSoC (when meaning the whole instrument), QICK

**Firmware**:
The bitstream loaded on the board (QICK).
_Avoid_: overlay, bitfile

**LO**:
The external local oscillator that shifts tones between the board's frequencies and the chip's frequencies.
_Avoid_: synthesizer, carrier

**IF**:
A frequency as seen at the board's ports, before up-conversion or after down-conversion.
_Avoid_: baseband (unless it is near zero), DDS frequency

**RF frequency**:
A frequency as seen by the chip; the one shown to the user.
_Avoid_: real frequency, physical frequency

**Image frequency**:
The second frequency (on the other side of the LO) that a real mixer also produces or receives for a given IF.
_Avoid_: mirror, ghost, unwanted sideband

## Chips and wiring

**Chip**:
One specific device under test, identified by name (e.g. "Transmon A").
_Avoid_: sample, DUT, device

**Chip type**:
The kind of chip: transmon or fluxonium.
_Avoid_: chip family, platform

**Readout line**:
The transmission line through the chip whose resonators are measured.
_Avoid_: feedline, probe line

**Control line**:
A separate line carrying microwave tones to drive the qubit; only fluxonium chips have one.
_Avoid_: drive line, flux line

**Flux bias**:
The DC current that sets the magnetic flux through a fluxonium's loop, and so its qubit frequency.
_Avoid_: flux, bias current, DC bias

**Output path**:
How tones leave the board toward the chip: **real** (one DAC into a real mixer) or **I/Q** (two DACs 90° apart into an I/Q mixer).
_Avoid_: upconversion scheme

**Return path**:
How the signal from the chip reaches the board: **real** (real mixer into one ADC) or **I/Q** (I/Q mixer into two ADCs, combined in software).
_Avoid_: downconversion scheme, input path

**Setup profile**:
The saved wiring of one chip: its output path, return path, ports, control line and LO.
_Avoid_: config, preset, setup

**Chip parameters**:
The values measured on one chip that later measurements start from, such as readout frequency, qubit frequency and π-pulse amplitude.
_Avoid_: calibration (reserved for I/Q calibration), chip config, qubit params

**I/Q calibration**:
The Q phase offset and Q/I gain ratio that best suppress the image of an I/Q output path; part of the setup profile.
_Avoid_: mixer correction, IQ balance

## Measurements

**Measurement**:
A kind of experiment the instrument can run, with its own parameters and plots (e.g. resonator sweep, two-tone, Rabi).
_Avoid_: experiment, program, script

**Run**:
One execution of a measurement with fixed parameters, producing data.
_Avoid_: shot (a single repetition inside a run), acquisition

**Readout tone**:
The tone sent through the readout line to probe a resonator.
_Avoid_: probe tone, measurement tone

**Qubit tone**:
The tone that drives the qubit transition, on the readout line (transmon) or control line (fluxonium).
_Avoid_: control tone, drive tone, pump

**Resonator sweep**:
A measurement of S21 (magnitude and phase of transmission) against readout tone frequency.
_Avoid_: VNA sweep, spectroscopy (alone), S21 scan

**CW Time**:
A measurement of S21 against time at one fixed readout tone frequency, repeated sweep after sweep until stopped; named after the PNA-X sweep type.
_Avoid_: time trace, stream, monitor

**Sweep** (in CW Time):
One pass of CW Time over its points; the screen redraws on each sweep, and the run saves every one.
_Avoid_: round (a round is one pass of averaging in the other measurements), frame

**Readout window**:
The time over which the board averages the returned signal into one I/Q value; the app's equivalent of the PNA-X's IF bandwidth (IF BW ≈ 1 / window).
_Avoid_: IF bandwidth, integration time, acquisition length

**Two-tone spectroscopy**:
A measurement that sweeps the qubit tone frequency while reading out at a fixed resonator frequency.
_Avoid_: qubit spectroscopy, pump-probe

**Rabi**:
A measurement that sweeps the qubit tone's amplitude or length and records the readout response.
_Avoid_: Rabi oscillation (for the measurement itself)

**Trace**:
One plotted curve from a run, such as S21 magnitude or phase.
_Avoid_: curve, plot, channel

## People

**Controller**:
The one user currently allowed to start and change runs on the board.
_Avoid_: owner, admin, operator

**Viewer**:
Any other user, who sees runs live but cannot change them.
_Avoid_: observer, guest
