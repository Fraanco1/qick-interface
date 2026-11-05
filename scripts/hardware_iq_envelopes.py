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
import Pyro4

from qick_interface import iq_delay
from qick_interface.board import QickBoard
from qick_interface.measurements.rabi import Rabi, RabiParams
from qick_interface.profiles import SetupProfile

board = QickBoard()
scope = Pyro4.Proxy(Pyro4.locateNS(host="192.168.3.1", port=8888).lookup("scope"))
iq = SetupProfile(chip="IQ", lo_mhz=None, output_path="iq", i_dac="DAC_A", q_dac="DAC_B", readout_adc="ADC_D")

found = iq_delay.measure(board, scope, iq)
print(f"Q delay measured: {found['iq_delay_ps']:.0f} ps (I on {found['i_channel']}, Q on {found['q_channel']})")
I_CH, Q_CH = found["i_channel"], found["q_channel"]

for cmd in (f"SELECT:{I_CH} ON", f"SELECT:{Q_CH} ON", "SELECT:CH2 ON", f"{I_CH}:COUPLING DC", f"{Q_CH}:COUPLING DC",
            f"{I_CH}:POSITION 0", f"{Q_CH}:POSITION 0", f"{I_CH}:SCALE 0.05", f"{Q_CH}:SCALE 0.05",
            "CH2:SCALE 1.0", "CH2:POSITION -3", "HORIZONTAL:DELAY:MODE OFF", "HORIZONTAL:POSITION 10",
            "ACQUIRE:MODE AVERAGE", "ACQUIRE:NUMAVG 64", "TRIGGER:A:TYPE EDGE", "TRIGGER:A:EDGE:SOURCE CH2",
            "TRIGGER:A:EDGE:SLOPE RISE", "TRIGGER:A:LEVEL:CH2 0.9", "TRIGGER:A:MODE NORMAL", "HORIZONTAL:SCALE 1e-7"):
    scope.write(cmd)


def capture():
    scope.write("ACQUIRE:STOPAFTER SEQUENCE")
    scope.write("ACQUIRE:STATE RUN")
    t0 = time.time()
    while scope.query("ACQUIRE:STATE?") != "0":
        if time.time() - t0 > 20:
            raise RuntimeError("no trigger")
        time.sleep(0.1)
    t, i = scope.waveform(I_CH)
    _, q = scope.waveform(Q_CH)
    return np.asarray(t), np.asarray(i), np.asarray(q)


def envelope(t, v, f_mhz):
    v = v - np.median(v)
    h = np.zeros(v.size)
    h[0] = 1
    h[1:(v.size + 1) // 2] = 2
    env = np.abs(np.fft.ifft(np.fft.fft(v) * h))
    n = max(1, int(round(1 / (f_mhz * 1e6) / (t[1] - t[0]))))
    return np.convolve(env, np.ones(n) / n, mode="same")


def centre_ns(t, env):
    """Centre of the envelope's top: weighted mean over where it is above half its peak."""
    top = env > env.max() / 2
    return np.sum(t[top] * env[top] ** 2) / np.sum(env[top] ** 2) * 1e9


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
            t, i, q = capture()
            window = t < 0.7e-6  # the qubit pulse; the readout pulse starts 1 µs after it
            ei, eq = envelope(t[window], i[window], 50), envelope(t[window], q[window], 50)
            ri, fi = edges_ns(t[window], ei)
            rq, fq = edges_ns(t[window], eq)
            print(f"{name}, {label}: Q − I at the rising edge {rq - ri:+.2f} ns, at the falling edge {fq - fi:+.2f} ns, "
                  f"centre {centre_ns(t[window], eq) - centre_ns(t[window], ei):+.2f} ns")
finally:
    board.silence()
    scope.write("ACQUIRE:MODE SAMPLE")
    scope.write("ACQUIRE:STOPAFTER RUNSTOP")
    scope.write("ACQUIRE:STATE RUN")
