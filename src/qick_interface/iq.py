"""Tones on the chip's output path: one DAC (real) or an I/Q pair.

A tone named "x" is the pulse "x" on the first DAC and, on the I/Q path, also "x_q" on the
Q DAC with the calibrated phase offset and gain ratio. Both pulses are frequency-matched to
the same readout, which keeps I and Q phase-locked.
"""
from dataclasses import dataclass

from .board import gen_channel
from .profiles import SetupProfile


@dataclass(frozen=True)
class _Output:
    suffix: str
    gen: int
    gain_factor: float
    phase_deg: float


def outputs(soccfg, profile: SetupProfile) -> list[_Output]:
    """The DAC(s) a tone goes out on. On the I/Q path the larger of I and Q gets the full gain;
    the sign of the Q phase picks the sideband."""
    if profile.output_path == "real":
        return [_Output("", gen_channel(soccfg, profile.readout_dac), 1.0, 0.0)]
    r = profile.iq_gain_ratio
    sign = 1 if profile.sideband == "upper" else -1
    return [_Output("", gen_channel(soccfg, profile.i_dac), 1 / max(1.0, r), 0.0),
            _Output("_q", gen_channel(soccfg, profile.q_dac), r / max(1.0, r), sign * profile.iq_phase_deg)]


class TonesMixin:
    """For AveragerProgramV2 subclasses: cfg["outputs"] holds the result of outputs()."""

    def declare_outputs(self, cfg):
        for out in cfg["outputs"]:
            self.declare_gen(ch=out.gen, nqz=1)

    def add_tone(self, cfg, name, freq, length, gain, **pulse_args):
        for out in cfg["outputs"]:
            self.add_pulse(ch=out.gen, name=name + out.suffix, ro_ch=cfg["ro"], style="const", freq=freq,
                           length=length, phase=out.phase_deg, gain=gain * out.gain_factor, **pulse_args)

    def play_tone(self, cfg, name, t=0):
        for out in cfg["outputs"]:
            self.pulse(ch=out.gen, name=name + out.suffix, t=t)
