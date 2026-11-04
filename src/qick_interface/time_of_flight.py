"""Time of flight: from the trigger to when a pulse sent on the readout output reaches the ADC.

A readout window opens together with a test pulse; where the pulse shows up in the recorded trace
is the time of flight (cables, chip and the board's own latency). Measured from the Setup panel.
"""
import math

import numpy as np
from qick.asm_v2 import AveragerProgramV2

from .frequency import plan_sweep
from .iq import TonesMixin, inputs, outputs, send_readouts
from .profiles import SetupProfile

PULSE_US = 1.0
WINDOW_US = 5.0      # finds arrivals up to WINDOW_US − PULSE_US
SHOTS = 100          # averaged, so a weak pulse through a cryostat still stands out
GAIN = 0.5
OFF_RESONANCE_MHZ = 20.0  # a hanger resonator would swallow a pulse right at the readout frequency


def pulse_rf_mhz(profile: SetupProfile, readout_freq_mhz: float | None) -> float:
    if readout_freq_mhz is not None:
        return readout_freq_mhz + OFF_RESONANCE_MHZ
    if profile.lo_mhz is None:
        return 500.0
    return profile.lo_mhz + (100.0 if profile.sideband == "upper" else -100.0)


class _Program(TonesMixin, AveragerProgramV2):
    def _initialize(self, cfg):
        self.declare_outputs(cfg)
        self.declare_inputs(cfg, length=cfg["window_us"])
        self.add_readout(cfg, "ro", freq=cfg["freq"])
        self.add_tone(cfg, "pulse", freq=cfg["freq"], gain=GAIN, length=cfg["pulse_us"])

    def _body(self, cfg):
        send_readouts(self, cfg, "ro")
        self.read(cfg, t=0)  # the window opens as the pulse leaves
        self.play_tone(cfg, "pulse", t=0)


def program(soccfg, profile: SetupProfile, readout_freq_mhz: float | None):
    rf = pulse_rf_mhz(profile, readout_freq_mhz)
    plan = plan_sweep(profile, rf, rf)
    ins = inputs(soccfg, profile)
    # the board keeps every shot's samples until the round ends: as many shots per round as fit
    ro = soccfg["readouts"][ins[0]]
    per_round = max(1, ro["buf_maxlen"] // math.ceil(WINDOW_US * ro["f_output"]))
    return _Program(soccfg, reps=per_round, final_delay=1.0, cfg={
        "outputs": outputs(soccfg, profile), "inputs": ins, "freq": plan.if_start,
        "rf_mhz": rf, "pulse_us": PULSE_US, "window_us": WINDOW_US, "time_of_flight": True,
        "rounds": math.ceil(SHOTS / per_round)})


def measure(board, profile: SetupProfile, readout_freq_mhz: float | None) -> float:
    """The time of flight in µs, to the nearest ns."""
    prog = program(board.soccfg, profile, readout_freq_mhz)
    traces = board.capture(prog)
    f_s = board.soccfg["readouts"][prog.cfg["inputs"][0]]["f_output"]
    return round(float(_arrival_us(np.sqrt(sum(np.abs(t) ** 2 for t in traces)), f_s)), 3)


def _arrival_us(amplitude: np.ndarray, f_s: float) -> float:
    """Where the amplitude first reaches half of the pulse's level (interpolated between samples)."""
    noise = np.median(amplitude)  # the pulse fills a fifth of the window: the median is the noise
    level = np.median(amplitude[amplitude > amplitude.max() / 2])
    if level < 10 * noise:
        raise ValueError(f"No pulse came back within {WINDOW_US - PULSE_US:g} µs. "
                         "Check the readout output and input of the setup, and the cables.")
    i = int(np.argmax(amplitude >= level / 2))
    if i == 0:
        return 0.0
    before, after = amplitude[i - 1], amplitude[i]
    return (i - 1 + (level / 2 - before) / (after - before)) / f_s
