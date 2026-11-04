"""Q delay: how far the Q DAC's output runs ahead of the I DAC's, measured on the oscilloscope for the
Setup panel's Measure key.

The two DACs sit on different converter tiles, whose relative delay is set anew at every power-up
(docs/research/dac-tile-sync.md). A delay τ shows up as a Q−I phase of φ0 + 360°·f·τ. The measurement
finds which scope channels carry the I and Q DACs (one DAC at a time), then plays an I/Q tone at a few
frequencies with no correction and fits that line. Both scope cables must be the same length.
"""
import time

import numpy as np

from .profiles import SetupProfile
from .tone import OutputTone, tone_program

CHANNELS = ("CH1", "CH2", "CH3", "CH4")
FREQS_MHZ = (20.0, 50.0, 100.0, 150.0)  # within the scope's 200 MHz; 50 MHz steps unwrap up to ±10 ns
GAIN = 0.3
MIN_VOLTS = 0.01  # a DAC whose tone is weaker than this on every channel is not cabled to the scope
WINDOW_S = 4e-6
FIT_POINTS = 4000
ACQUIRE_TIMEOUT_S = 5.0  # a capture takes ~0.7 s (mains trigger, plus the link)  # 4 µs at 1 GS/s: hundreds of carrier cycles even at 20 MHz


def measure(board, scope, profile: SetupProfile) -> dict:
    if profile.output_path != "iq":
        raise ValueError("The Q delay is a property of the I/Q output path; set Output path to I/Q.")
    # the DAC outputs themselves: no LO (RF = DAC frequency), no calibration, no correction
    raw = profile.model_copy(update={"lo_mhz": None, "sideband": "upper", "iq_phase_deg": 90.0,
                                     "iq_gain_ratio": 1.0, "iq_delay_ps": 0.0})
    saved = _setup(scope)
    try:
        i_ch = _find_channel(board, scope, raw, raw.i_dac)
        q_ch = _find_channel(board, scope, raw, raw.q_dac)
        if i_ch == q_ch:
            raise ValueError(f"{raw.i_dac} and {raw.q_dac} both show on {i_ch}; cable them to separate channels.")
        phases = []
        for f in FREQS_MHZ:
            _play(board, raw, f)
            _acquire(scope)  # I and Q from the same acquisition
            phases.append(_fit(scope, q_ch, f)[1] - _fit(scope, i_ch, f)[1])
    finally:
        board.silence()
        _restore(scope, saved)
    unwrapped = np.degrees(np.unwrap(np.radians(phases)))
    slope, at_zero = np.polyfit(FREQS_MHZ, unwrapped, 1)  # degrees per MHz, degrees
    scatter = np.std(unwrapped - (slope * np.asarray(FREQS_MHZ) + at_zero))
    if scatter > 3:
        raise ValueError(f"The Q−I phase does not follow a single delay (scatter {scatter:.1f}°). "
                         "Check that the scope cables are the same length and firmly connected.")
    return {"iq_delay_ps": round(slope / 360 * 1e6), "i_channel": i_ch, "q_channel": q_ch,
            "phase_at_0_deg": round(float(at_zero % 360), 1)}


def _setup(scope) -> dict:
    """Show every channel at a scale that fits the tone; trigger on the mains. Returns what to restore."""
    keys = [f"{ch}:{k}" for ch in CHANNELS for k in ("SCALE", "POSITION")] + \
           [f"SELECT:{ch}" for ch in CHANNELS] + ["HORIZONTAL:SCALE", "TRIGGER:A:EDGE:SOURCE", "TRIGGER:A:MODE", "ACQUIRE:STOPAFTER"]
    saved = {k: scope.query(f"{k}?") for k in keys}
    for ch in CHANNELS:
        scope.write(f"SELECT:{ch} ON")
        scope.write(f"{ch}:SCALE 0.05")
        scope.write(f"{ch}:POSITION 0")
    scope.write(f"HORIZONTAL:SCALE {WINDOW_S / 10:.1e}")
    scope.write("TRIGGER:A:EDGE:SOURCE LINE")  # the mains: always fires; the I−Q phase does not care when
    scope.write("TRIGGER:A:MODE NORMAL")
    return saved


def _restore(scope, saved: dict):
    for key, value in saved.items():
        scope.write(f"{key} {value}")
    scope.write("ACQUIRE:STATE RUN")


def _play(board, profile, f_mhz):
    board.play(tone_program(board.soccfg, profile, OutputTone(chip=profile.chip, rf_mhz=f_mhz, gain=GAIN)))


def _acquire(scope):
    scope.write("ACQUIRE:STOPAFTER SEQUENCE")
    scope.write("ACQUIRE:STATE RUN")
    deadline = time.monotonic() + ACQUIRE_TIMEOUT_S
    while scope.query("ACQUIRE:STATE?") != "0":
        if time.monotonic() > deadline:
            raise RuntimeError(f"The oscilloscope did not finish an acquisition within {ACQUIRE_TIMEOUT_S} s.")
        time.sleep(0.05)


def _find_channel(board, scope, profile, dac: str) -> str:
    """Play a tone on one DAC alone and return the channel it shows on."""
    _play(board, profile.model_copy(update={"output_path": "real", "readout_dac": dac}), 50.0)
    _acquire(scope)
    amplitudes = {ch: _fit(scope, ch, 50.0)[0] for ch in CHANNELS}
    best = max(amplitudes, key=amplitudes.get)
    if amplitudes[best] < MIN_VOLTS:
        raise ValueError(f"{dac} does not show on any scope channel; cable it to one.")
    return best


def _fit(scope, ch, f_mhz):
    """Amplitude (V) and phase (deg) of a cosine at f_mhz in the channel's last acquisition."""
    t, v = scope.waveform(ch)
    t, v = np.asarray(t)[:FIT_POINTS], np.asarray(v)[:FIT_POINTS]
    w = 2 * np.pi * f_mhz * 1e6 * t
    (c, s, _), *_ = np.linalg.lstsq(np.column_stack([np.cos(w), np.sin(w), np.ones_like(t)]), v, rcond=None)
    return float(np.hypot(c, s)), float(np.degrees(np.arctan2(-s, c)))
