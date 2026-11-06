"""Tones on the chip's output path (one DAC, or an I/Q pair), and readouts on its return path
(one ADC, or an I/Q pair).

A tone named "x" is the pulse "x" on the first DAC and, on the I/Q path, also "x_q" on the
Q DAC with the calibrated phase offset and gain ratio. The Q delay (Q's DAC running ahead of I's) is
taken off Q's carrier phase at each frequency, and off the envelope's timing: the leading DAC starts
its pulse later by whole clock cycles, and a Gaussian envelope on it is shifted by the remaining
fraction of a cycle. A flat pulse can only move by whole cycles (within 0.8 ns). Both pulses are frequency-matched to
the readouts, which keeps everything phase-locked. On the I/Q return path the I and Q readouts
share one readout config and are triggered together.
"""
from dataclasses import dataclass

import numpy as np
from qick.asm_v2 import QickParam

from .board import gen_channel, readout_channel
from .profiles import SetupProfile


@dataclass(frozen=True)
class _Output:
    suffix: str
    gen: int
    gain_factor: float
    phase_deg: float
    lead_ps: float = 0.0  # how far this DAC runs ahead of the I DAC; taken off its phase at each frequency
    # Q from the TX I/Q table: (IFs, phases, gain factors) to interpolate at the tone's IF, in place of
    # phase_deg and gain_factor
    table: tuple | None = None

    def phase_at(self, freq):
        return self.phase_deg if self.table is None else along(self.table[0], self.table[1], freq)

    def gain_at(self, freq):
        return self.gain_factor if self.table is None else along(self.table[0], self.table[2], freq)


def along(xs, ys, freq):
    """ys interpolated at freq (held beyond the ends). A frequency sweep gets the straight line between the
    values at its two ends: a QICK sweep can only change a pulse parameter linearly."""
    if isinstance(freq, QickParam) and freq.is_sweep():
        if len(freq.spans) != 1:
            raise ValueError("An I/Q table can follow a sweep of one loop only.")
        lo = freq.start
        hi = lo + next(iter(freq.spans.values()))
        y0, y1 = np.interp([lo, hi], xs, ys)
        return float(y0) + (freq - lo) * float((y1 - y0) / (hi - lo))
    return float(np.interp(float(freq), xs, ys))


def outputs(soccfg, profile: SetupProfile) -> list[_Output]:
    """The DAC(s) a tone goes out on. On the I/Q path the larger of I and Q gets the full gain;
    the sign of the Q phase picks the sideband, and Q's lead over I (iq_delay_ps) is corrected."""
    if profile.output_path == "real":
        return [_Output("", gen_channel(soccfg, profile.readout_dac), 1.0, 0.0)]
    sign = 1 if profile.sideband == "upper" else -1
    q_gen = gen_channel(soccfg, profile.q_dac)
    if profile.iq_table:
        ifs, phases, ratios = (np.array(c, dtype=float) for c in zip(*profile.iq_table))
        top = max(1.0, ratios.max())  # I keeps one gain for every IF; Q follows the table
        return [_Output("", gen_channel(soccfg, profile.i_dac), 1 / top, 0.0),
                _Output("_q", q_gen, 1.0, 0.0, profile.iq_delay_ps, table=(ifs, sign * phases, ratios / top))]
    r = profile.iq_gain_ratio
    return [_Output("", gen_channel(soccfg, profile.i_dac), 1 / max(1.0, r), 0.0),
            _Output("_q", q_gen, r / max(1.0, r), sign * profile.iq_phase_deg, profile.iq_delay_ps)]


def tone_gain(program, name: str):
    """The gain a tone was asked for (0–1), as QICK rounded it, on either output path:
    on the I/Q path the I pulse carries it scaled by its gain factor."""
    return program.get_pulse_param(name, "gain", as_array=True) / program.cfg["outputs"][0].gain_factor


def control_outputs(soccfg, profile: SetupProfile) -> list[_Output]:
    """The DAC(s) the qubit tone goes out on: the control line's own DAC, else the readout line's."""
    if profile.control_dac:
        return [_Output("", gen_channel(soccfg, profile.control_dac), 1.0, 0.0)]
    return outputs(soccfg, profile)


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
    cfg["inputs"] the result of inputs(), and cfg["control"] (programs with a qubit tone) the result
    of control_outputs(). A tone added with line="control" goes out there."""

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
        for gen in {out.gen for out in cfg["outputs"] + cfg.get("control", [])}:
            self.declare_gen(ch=gen, nqz=1)

    def add_tone(self, cfg, name, freq, gain, line="outputs", **pulse_args):
        """A constant pulse by default; pass style="arb" and envelope= for a shaped one."""
        pulse_args.setdefault("style", "const")
        self._tone_lines = {**getattr(self, "_tone_lines", {}), name: line}
        # the DAC that runs ahead starts later; a shaped envelope takes the remainder (add_gauss_envelope)
        whole = round if pulse_args["style"] == "const" else np.floor
        self._tone_starts = {**getattr(self, "_tone_starts", {}),
                             name: [whole(lag / cycle) * cycle * 1e-6 for lag, cycle in self._lags(cfg[line])]}
        for out in cfg[line]:
            # a DAC running τ ahead adds 360°·f·τ; freq may be a sweep, and the phase then sweeps with it
            phase = out.phase_at(freq)
            if out.lead_ps:
                phase = phase - freq * (360e-6 * out.lead_ps)
            factor = out.gain_at(freq)
            if isinstance(factor, QickParam) and isinstance(gain, QickParam) and gain.is_sweep():
                raise ValueError("With an I/Q table, a sweep can't change the gain and the IF together.")
            self.add_pulse(ch=out.gen, name=name + out.suffix, ro_ch=cfg["inputs"][0], freq=freq,
                           phase=phase, gain=gain * factor if not isinstance(factor, QickParam) else factor * gain,
                           **pulse_args)

    def _lags(self, outs):
        """For each output: how much later it must play to line up with the slowest DAC (ps), and its
        clock cycle (ps)."""
        first = min(out.lead_ps for out in outs)
        return [(out.lead_ps - first, 1e6 / self.soccfg["gens"][out.gen]["f_fabric"]) for out in outs]

    def add_gauss_envelope(self, cfg, name, sigma, length, line="outputs", flat_top=False):
        """A Gaussian envelope, as QICK's add_gauss(even_length=True) samples it. On a DAC that must play
        later by a fraction of a clock cycle, the Gaussian is shifted by that fraction. flat_top: the
        envelope is split into the edges of a flat_top pulse; the falling half then starts at the top."""
        for out, (lag, cycle) in zip(cfg[line], self._lags(cfg[line])):
            fraction_ps = lag - np.floor(lag / cycle) * cycle
            if fraction_ps == 0:
                self.add_gauss(ch=out.gen, name=name, sigma=sigma, length=length, even_length=True)
                continue
            gen = self.soccfg["gens"][out.gen]
            per_clk = gen["samps_per_clk"]
            samples = 2 * self.us2cycles(gen_ch=out.gen, us=length / 2) * per_clk  # as add_gauss counts them
            sig = self.us2cycles(gen_ch=out.gen, us=sigma / (np.sqrt(2.0) if self.GAUSS_BUG else 1.0),
                                 as_float=True) * per_clk
            shift = fraction_ps * 1e-6 * gen["f_fabric"] * per_clk  # in samples
            x = np.arange(samples) - shift  # where each sample falls on the unshifted envelope
            env = self.soccfg.get_maxv(out.gen) * np.exp(-(x - (samples / 2 - 0.5)) ** 2 / (2 * sig ** 2))
            env[x < 0] = 0  # before the envelope starts
            if flat_top:  # still on the flat part, which plays between the two halves
                env[(np.arange(samples) >= samples // 2) & (x < samples // 2)] = self.soccfg.get_maxv(out.gen)
            self.add_envelope(ch=out.gen, name=name, idata=env)

    def play_tone(self, cfg, name, t=0):
        for out, later in zip(cfg[self._tone_lines[name]], self._tone_starts[name]):
            self.pulse(ch=out.gen, name=name + out.suffix, t=t + later)
