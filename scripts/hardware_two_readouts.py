"""Manual bench check for the I/Q return path: is the phase between two readouts the same every run?

Wiring: a DAC (DAC_B unless given) -> power splitter -> ADC_D and ADC_C (equal cables if possible). No mixer,
no LO. The sweep stays in 0.5-2 GHz, inside a ZN2PD-183W-S+ splitter's range (0.5-18 GHz) and the ADCs' IF limit.
Both readouts then see the same signal, so Y_C / Y_D should be a fixed complex number: its phase may
vary with frequency (the cable difference, a delay) but must repeat from run to run. If it doesn't,
the two readouts' reference oscillators are not locked and the I/Q return path can't be calibrated.
Usage: .venv/bin/python scripts/hardware_two_readouts.py [runs] [DAC_A or DAC_B]
"""
import sys

import numpy as np

from qick_interface.board import QickBoard
from qick_interface.measurements.resonator_sweep import ResonatorSweep, ResonatorSweepParams
from qick_interface.profiles import SetupProfile

runs = int(sys.argv[1]) if len(sys.argv) > 1 else 10
dac = sys.argv[2] if len(sys.argv) > 2 else "DAC_B"
profile = SetupProfile(chip="Splitter", lo_mhz=None, readout_dac=dac,
                       return_path="iq", i_adc="ADC_D", q_adc="ADC_C")
params = ResonatorSweepParams(rf_start_mhz=500.0, rf_stop_mhz=2000.0, points=151, averages=200, rounds=1)

board = QickBoard()
ratios = []
for run in range(runs):  # a new program each run: oscillators are set up again every time
    program, if_mhz, _ = ResonatorSweep.program(board, profile, params)
    iq = next(board.run(program, 1))
    ratios.append(iq[1] / iq[0])
    print(f"run {run + 1}: |C/D| {np.mean(np.abs(ratios[-1])):.4f}, "
          f"phase at {if_mhz[0]:.0f} MHz {np.degrees(np.angle(ratios[-1][0])):8.3f}°")

ratios = np.array(ratios)
spread = np.degrees(np.std(np.angle(ratios / ratios[0]), axis=0))
slope = np.polyfit(if_mhz, np.unwrap(np.angle(ratios.mean(axis=0))), 1)[0]
print(f"\nPhase spread between runs: max {spread.max():.3f}° (must be well under 1°)")
print(f"Delay between the two paths: {slope / (2 * np.pi) * 1e6:.1f} ps (cables + board)")
