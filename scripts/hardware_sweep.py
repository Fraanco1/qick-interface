"""Manual hardware check: resonator sweep on the real board, with timing.

Default wiring is the bench loopback DAC_B -> ADC_D with no LO.
Usage: .venv/bin/python scripts/hardware_sweep.py [rf_start rf_stop points]
"""
import sys
import time

import numpy as np

from qick_interface.board import QickBoard
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
