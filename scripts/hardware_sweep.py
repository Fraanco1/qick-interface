"""Manual hardware check: resonator sweep, then CW Time, on the real board, with timing.

Default wiring is the bench loopback DAC_B -> ADC_D with no LO.
Usage: .venv/bin/python scripts/hardware_sweep.py [rf_start rf_stop points]
"""
import sys
import time

import numpy as np

from qick_interface.board import QickBoard
from qick_interface.measurements.cw_time import CwTime, CwTimeParams
from qick_interface.measurements.resonator_sweep import ResonatorSweep, ResonatorSweepParams
from qick_interface.profiles import SetupProfile

start, stop, points = (float(sys.argv[1]), float(sys.argv[2]), int(sys.argv[3])) if len(sys.argv) > 3 else (100.0, 1000.0, 1001)
profile = SetupProfile(chip="Loopback", chip_type="transmon", lo_mhz=None, readout_dac="DAC_B", readout_adc="ADC_D")
params = ResonatorSweepParams(rf_start_mhz=start, rf_stop_mhz=stop, points=points, averages=100, rounds=5)

board = QickBoard()
t0 = time.perf_counter()
for u in ResonatorSweep.run(board, profile, params):
    mag, ph = u.traces["|S21| (dB)"], u.traces["Phase (°)"]
    print(f"round {u.round}/{u.rounds} at {time.perf_counter() - t0:6.2f} s: "
          f"|S21| {mag.min():.1f}..{mag.max():.1f} dB, phase spread {np.ptp(ph):.1f}°")
print(f"{points} points x {params.averages} averages x {params.rounds} rounds in {time.perf_counter() - t0:.2f} s")

# CW Time at the middle of the sweep. Back-to-back windows must all arrive (no stall), the level must match
# the sweep, and the point-to-point noise should fall as 1/sqrt(window).
freq = (start + stop) / 2
level = np.interp(freq, u.x, mag)
print(f"\nCW Time at {freq:g} MHz; resonator sweep there: {level:.2f} dB")
for window, points, averages in [(0.5, 1001, 1), (1.5, 1001, 1), (10, 1001, 1), (100, 201, 1), (1, 10001, 10)]:
    sweeps = []
    cw = CwTimeParams(freq_mhz=freq, points=points, readout_length_us=window, averages=averages)
    t0 = time.perf_counter()
    for v in CwTime.run(board, profile, cw, should_stop=lambda: len(sweeps) >= 5):
        sweeps.append(v)
    elapsed = time.perf_counter() - t0
    s21 = np.asarray(sweeps[-1].raw["s21"])
    noise_db = 20 * np.log10(1 + np.std(np.abs(s21[-1])) / np.mean(np.abs(s21[-1])))
    drift = np.degrees(np.ptp(np.angle(s21.mean(axis=1))))
    print(f"window {window:5g} µs x {averages:2d} x {points:5d} points: {len(sweeps)} sweeps in {elapsed:5.2f} s, "
          f"|S21| {20 * np.log10(np.mean(np.abs(s21))):.2f} dB, point noise {noise_db:.4f} dB, "
          f"phase drift between sweeps {drift:.2f}°")

# Timing: the slope of sweep period against points is the real time per point (the fixed transfer overhead
# between sweeps cancels). It should equal averages x spacing; a late trigger on every shot would show here.
periods = {}
for points in (2001, 10001):
    cw = CwTimeParams(freq_mhz=freq, points=points, readout_length_us=1.0, averages=10)
    ends = []
    for v in CwTime.run(board, profile, cw, should_stop=lambda: len(ends) >= 8):
        ends = v.raw["sweep_end_unix_s"]
    periods[points] = np.median(np.diff(ends[2:]))  # skip the first sweeps (program load)
per_point_us = (periods[10001] - periods[2001]) / 8000 * 1e6
expected_us = (v.x[1] - v.x[0]) * {"µs": 1, "ms": 1e3, "s": 1e6}[v.x_axis["unit"]]
print(f"\nCW Time timing: {per_point_us:.4f} µs per point measured, {expected_us:.4f} µs expected "
      f"(sweep periods {periods[2001] * 1e3:.1f} and {periods[10001] * 1e3:.1f} ms)")
