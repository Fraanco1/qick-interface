"""Manual bench check of the whole I/Q chain without mixers or LO: the I/Q output's two DACs cabled straight
into the I/Q return's two ADCs, which stand in for an ideal I/Q mixer pair at the IF.

Wiring: DAC_A (I) -> ADC_D (I; or ADC_B, given as an argument), DAC_B (Q) -> ADC_C (Q), cables of equal length.

1. RX I/Q calibration, several runs: the gain ratio, phase and delay it finds must repeat. Expected:
   - phase near 180°: here Q leads I by 90° (the output path's Q), while the convention is that of a
     downconverting mixer on the upper sideband, where Q lags I;
   - delay = this power-up's DAC tile skew (the setup's Q delay is 0, so nothing corrects it) plus the
     ~8 ps between the ADC_C and ADC_D paths (splitter check, docs/hardware-setup.md; unmeasured for ADC_B);
   - gain ratio = DAC_B/DAC_A output ratio x ADC_C/ADC_D (0.994).
2. With that calibration applied: the image rejection actually reached, |Y_I + j·Y_Q| against
   |Y_I − j·Y_Q| (Y_Q corrected), at every frequency.

Usage: .venv/bin/python scripts/hardware_iq_loop.py [runs] [I ADC, default ADC_D]
"""
import sys

import numpy as np

from qick_interface.board import QickBoard
from qick_interface.iq import rx_imbalance
from qick_interface.measurements.resonator_sweep import ResonatorSweep, ResonatorSweepParams
from qick_interface.measurements.rx_iq_cal import RxIqCal, RxIqCalParams
from qick_interface.profiles import SetupProfile

runs = int(sys.argv[1]) if len(sys.argv) > 1 else 5
i_adc = sys.argv[2] if len(sys.argv) > 2 else "ADC_D"
profile = SetupProfile(chip="I/Q loop", lo_mhz=None, output_path="iq", i_dac="DAC_A", q_dac="DAC_B",
                       return_path="iq", i_adc=i_adc, q_adc="ADC_C", time_of_flight_us=0.292)
band = dict(rf_start_mhz=100.0, rf_stop_mhz=1500.0, points=141, averages=200, rounds=1)

board = QickBoard()
print("1. RX I/Q calibration, 100-1500 MHz")
found = []
for run in range(runs):
    info = list(RxIqCal.run(board, profile, RxIqCalParams(**band)))[-1].info
    found.append(info)
    print(f"  run {run + 1}: Q/I gain {info['Q/I gain']:.4f}, Q phase {info['Q phase (°)']:8.2f}°, "
          f"I/Q delay {info['I/Q delay (ps)']:7.1f} ps, image rejection (estimate) {info['Image rejection (dB)']:.1f} dB")

gains = np.array([f["Q/I gain"] for f in found])
phases = np.array([f["Q phase (°)"] for f in found])
delays = np.array([f["I/Q delay (ps)"] for f in found])
mean_phase = np.degrees(np.angle(np.mean(np.exp(1j * np.radians(phases)))))  # phases near ±180° wrap
spread = np.degrees(np.abs(np.angle(np.exp(1j * np.radians(phases - mean_phase))))).max()
print(f"  spread between runs: gain {np.ptp(gains):.4f}, phase {spread:.3f}°, delay {np.ptp(delays):.1f} ps")

print("\n2. Image rejection with that calibration applied")
cal = profile.model_copy(update={"rx_gain_ratio": float(gains.mean()), "rx_phase_deg": float(mean_phase),
                                 "rx_delay_ps": float(delays.mean())})
program, if_mhz, _ = ResonatorSweep.program(board, cal, ResonatorSweepParams(**band))
iq = next(board.run(program, 1))
y_i, y_q = iq[0], iq[1] / rx_imbalance(cal, if_mhz)
rejection = 20 * np.log10(np.abs(y_i + 1j * y_q) / np.maximum(np.abs(y_i - 1j * y_q), 1e-12))
for lo, hi in ((100, 500), (500, 1000), (1000, 1500)):
    band_rej = rejection[(if_mhz >= lo) & (if_mhz <= hi)]
    print(f"  {lo:4d}-{hi:4d} MHz: median {np.median(band_rej):.1f} dB, worst {band_rej.min():.1f} dB")
