"""Tones on the chip's output path (one DAC, or an I/Q pair), and readouts on its return path
(one ADC, or an I/Q pair).

A tone named "x" is the pulse "x" on the first DAC and, on the I/Q path, also "x_q" on the
Q DAC with the calibrated phase offset and gain ratio. Both pulses are frequency-matched to
the readouts, which keeps everything phase-locked. On the I/Q return path the I and Q readouts
share one readout config and are triggered together.
"""
from dataclasses import dataclass

import numpy as np

from .board import gen_channel, readout_channel
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


def tone_gain(program, name: str):
    """The gain a tone was asked for (0–1), as QICK rounded it, on either output path:
    on the I/Q path the I pulse carries it scaled by its gain factor."""
    return program.get_pulse_param(name, "gain", as_array=True) / program.cfg["outputs"][0].gain_factor


def inputs(soccfg, profile: SetupProfile) -> list[int]:
    """The readout(s) the chip's signal comes back on: [I, Q] on the I/Q return path."""
    if profile.return_path == "iq":
        return [readout_channel(soccfg, profile.i_adc), readout_channel(soccfg, profile.q_adc)]
    return [readout_channel(soccfg, profile.readout_adc)]


def rx_imbalance(profile: SetupProfile, if_mhz):
    """The calibrated Q/I imbalance of the I/Q return path at each IF: g·e^{j(φ + 2π·f·τ)}."""
    phase = np.radians(profile.rx_phase_deg) + 2 * np.pi * np.asarray(if_mhz) * profile.rx_delay_ps * 1e-6
    return profile.rx_gain_ratio * np.exp(1j * phase)


def send_readouts(asm, cfg, name: str, t=0):
    """Push a readout config to every input; asm is the program, or an AsmV2 block for a loop."""
    for ro in cfg["inputs"]:
        asm.send_readoutconfig(ch=ro, name=name, t=t)


class TonesMixin:
    """For AveragerProgramV2 subclasses: cfg["outputs"] holds the result of outputs(),
    cfg["inputs"] the result of inputs()."""

    def declare_inputs(self, cfg, length):
        for ro in cfg["inputs"]:
            self.declare_readout(ch=ro, length=length)

    def add_readout(self, cfg, name, freq):
        """One readout config for all inputs, frequency-matched to the output."""
        self.add_readoutconfig(ch=cfg["inputs"], name=name, freq=freq, gen_ch=cfg["outputs"][0].gen)

    def read(self, cfg, t, pins=None):
        """Open the readout window on every input at once (and raise the PMOD pins, if given)."""
        self.trigger(ros=cfg["inputs"], pins=pins, t=t)

    def declare_outputs(self, cfg):
        for out in cfg["outputs"]:
            self.declare_gen(ch=out.gen, nqz=1)

    def add_tone(self, cfg, name, freq, gain, **pulse_args):
        """A constant pulse by default; pass style="arb" and envelope= for a shaped one."""
        pulse_args.setdefault("style", "const")
        for out in cfg["outputs"]:
            self.add_pulse(ch=out.gen, name=name + out.suffix, ro_ch=cfg["inputs"][0], freq=freq,
                           phase=out.phase_deg, gain=gain * out.gain_factor, **pulse_args)

    def add_gauss_envelope(self, cfg, name, sigma, length):
        for out in cfg["outputs"]:
            self.add_gauss(ch=out.gen, name=name, sigma=sigma, length=length, even_length=True)

    def play_tone(self, cfg, name, t=0):
        for out in cfg["outputs"]:
            self.pulse(ch=out.gen, name=name + out.suffix, t=t)
