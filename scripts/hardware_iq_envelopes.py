"""Manual bench check: do the I and Q pulse envelopes leave the DACs together once the Q delay is applied?

Wiring: DAC_A (I) and DAC_B (Q) on two scope channels with equal cables, PMOD0_0 on CH2, the scope's USB to
the board. The app must not be running. It measures the Q delay as Setup -> I/Q cal -> Measure does, then
plays I/Q Rabi shots (a Gaussian, and Gaussian edges) without and with the correction, and prints how far
Q's envelope edges are from I's. Expected: about the Q delay (ns) without, under ~0.1 ns with.
This script changes the scope's settings.

    .venv/bin/python scripts/hardware_iq_envelopes.py
"""
import time

import numpy as np

from qick_interface import iq_delay
from qick_interface.board import QickBoard
from qick_interface.measurements.rabi import Rabi, RabiParams
from qick_interface.profiles import SetupProfile

board = QickBoard()
scope = board.scope()
iq = SetupProfile(chip="IQ", lo_mhz=None, output_path="iq", i_dac="DAC_A", q_dac="DAC_B", readout_adc="ADC_D")

found = iq_delay.measure(board, scope, iq)
print(f"Q delay measured: {found['iq_delay_ps']:.0f} ps (I on {found['i_channel']}, Q on {found['q_channel']})")
I_CH, Q_CH = found["i_channel"], found["q_channel"]

for cmd in (f"SELECT:{I_CH} ON", f"SELECT:{Q_CH} ON", "SELECT:CH2 ON", f"{I_CH}:COUPLING DC", f"{Q_CH}:COUPLING DC",
            f"{I_CH}:POSITION 0", f"{Q_CH}:POSITION 0", f"{I_CH}:SCALE 0.05", f"{Q_CH}:SCALE 0.05",
            "CH2:SCALE 1.0", "CH2:POSITION -3", "HORIZONTAL:DELAY:MODE OFF", "HORIZONTAL:POSITION 10",
            "ACQUIRE:MODE SAMPLE", "TRIGGER:A:TYPE EDGE", "TRIGGER:A:EDGE:SOURCE CH2",
            "TRIGGER:A:EDGE:SLOPE RISE", "TRIGGER:A:LEVEL:CH2 0.9", "TRIGGER:A:MODE NORMAL", "HORIZONTAL:SCALE 1e-7"):
    scope.write(cmd)


SHOTS = 8  # the MSO2024B never offers its own averaged waveform for reading (CURVE? times out), so: here
WINDOW_S = (-0.05e-6, 0.7e-6)  # the qubit pulse: the record also holds the shot before, and the readout 1 µs later


def capture(f_mhz):
    """SHOTS single acquisitions, each triggered by PMOD0_0 at the start of the shot: the time axis, and I's
    and Q's envelopes averaged over them. Envelopes, not waveforms: the carrier's phase differs from shot
    to shot, and averaging the waveforms would partly cancel it."""
    ei, eq = [], []
    for _ in range(SHOTS):
        scope.write("ACQUIRE:STOPAFTER SEQUENCE")
        scope.write("ACQUIRE:STATE RUN")
        t0 = time.time()
        while scope.query("ACQUIRE:STATE?") != "0":
            if time.time() - t0 > 20:
                raise RuntimeError("no trigger")
            time.sleep(0.1)
        t, i = (np.asarray(x) for x in scope.waveform(I_CH))
        q = np.asarray(scope.waveform(Q_CH)[1])
        w = (t > WINDOW_S[0]) & (t < WINDOW_S[1])
        ei.append(envelope(t[w], i[w], f_mhz))
        eq.append(envelope(t[w], q[w], f_mhz))
    return t[w], np.mean(ei, axis=0), np.mean(eq, axis=0)


def envelope(t, v, f_mhz):
    v = v - np.median(v)
    h = np.zeros(v.size)
    h[0] = 1
    h[1:(v.size + 1) // 2] = 2
    env = np.abs(np.fft.ifft(np.fft.fft(v) * h))
    n = max(1, int(round(1 / (f_mhz * 1e6) / (t[1] - t[0]))))
    return np.convolve(env, np.ones(n) / n, mode="same")


def lag_ns(t, a, b):
    """How much later b is than a, from the cross-correlation of the whole envelopes (refined between samples)."""
    c = np.correlate(b - b.mean(), a - a.mean(), "full")
    k = np.argmax(c)
    frac = (c[k - 1] - c[k + 1]) / (2 * (c[k - 1] - 2 * c[k] + c[k + 1]))
    return (k - (a.size - 1) + frac) * (t[1] - t[0]) * 1e9


def edges_ns(t, env):
    above = np.flatnonzero(env >= env.max() / 2)
    i, j = above[0], above[-1]
    half = env.max() / 2
    rise = t[i - 1] + (half - env[i - 1]) / (env[i] - env[i - 1]) * (t[i] - t[i - 1])
    fall = t[j] + (env[j] - half) / (env[j] - env[j + 1]) * (t[j + 1] - t[j])
    return rise * 1e9, fall * 1e9


shapes = {
    "Gaussian σ 20 ns": RabiParams(qubit_freq_mhz=50, readout_freq_mhz=90, sigma_us=0.02, scope_gain=0.5,
                                   final_delay_us=5, readout_gap_us=1.0),
    "Gaussian edges σ 10 ns, flat 0.1 µs": RabiParams(qubit_freq_mhz=50, readout_freq_mhz=90, sweep="length",
                                                      shape="gaussian edges", edge_sigma_us=0.01, qubit_gain=0.5,
                                                      scope_length_us=0.1, final_delay_us=5, readout_gap_us=1.0),
}
try:
    for name, params in shapes.items():
        for label, delay in (("no correction", 0.0), ("with the Q delay", found["iq_delay_ps"])):
            board.play(Rabi.sequence(board.soccfg, iq.model_copy(update={"iq_delay_ps": delay}), params))
            time.sleep(0.3)
            t, ei, eq = capture(50)
            ri, fi = edges_ns(t, ei)
            rq, fq = edges_ns(t, eq)
            print(f"{name}, {label}: Q − I at the rising edge {rq - ri:+.2f} ns, at the falling edge {fq - fi:+.2f} ns, "
                  f"whole envelope {lag_ns(t, ei, eq):+.2f} ns")
finally:
    board.silence()
    scope.write("ACQUIRE:MODE SAMPLE")
    scope.write("ACQUIRE:STOPAFTER RUNSTOP")
    scope.write("ACQUIRE:STATE RUN")
