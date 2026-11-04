"""CW Time: |S21| and phase against time at one frequency, re-swept until Stop (PNA-X "CW Time")."""
import time
from collections.abc import Callable, Iterator

import numpy as np
from pydantic import BaseModel, Field
from qick.asm_v2 import AveragerProgramV2

from ..frequency import plan_sweep
from ..iq import TonesMixin, inputs, outputs, send_readouts
from ..profiles import SetupProfile
from .base import Update, received_s21


def _f(default, title, group, unit=None, **kw):
    extra = {"group": group, **({"unit": unit} if unit else {}), **kw.pop("extra", {})}
    return Field(default, title=title, json_schema_extra=extra, **kw)


class CwTimeParams(BaseModel):
    freq_mhz: float = _f(..., "Frequency", "Sweep", "MHz", extra={"from_chip": "readout_freq_mhz"})
    points: int = _f(201, "Points", "Sweep", ge=2, le=10001)
    gain: float = _f(0.5, "Gain", "Power", ge=0, le=1)
    readout_length_us: float = _f(10.0, "Readout window", "Timing", "µs", ge=0.1, le=100,
                                  description="Windows follow each other (gaps under 2 ns); a longer window averages more noise away.")
    settle_us: float = _f(10.0, "Settling time", "Timing", "µs", ge=0, le=1000,
                          description="Wait after the tone starts, before the first point of each sweep.")
    averages: int = _f(1, "Averages per point", "Average", ge=1, le=1000,
                       description="Back-to-back windows averaged into each point.")


class _Program(TonesMixin, AveragerProgramV2):
    """The tone starts once and never stops; the readout windows follow each other at a fixed spacing.
    Each round of the program is one sweep."""

    def _initialize(self, cfg):
        self.declare_outputs(cfg)
        self.declare_inputs(cfg, length=cfg["readout_length"])
        self.add_readout(cfg, "ro", freq=cfg["freq"])
        self.add_tone(cfg, "probe", freq=cfg["freq"], length=1.0, gain=cfg["gain"], mode="periodic")
        self.add_loop("point", cfg["points"])
        send_readouts(self, cfg, "ro")
        self.play_tone(cfg, "probe", t=0)
        self.delay_auto(t=cfg["settle"], gens=False)  # settling counts from the tone's start

    def _body(self, cfg):
        self.read(cfg, t=0)
        self.delay(t=cfg["spacing"])  # the next window opens as this one closes


class CwTime:
    name = "CW Time"
    Params = CwTimeParams
    x_axis = {"title": "Time", "unit": "µs"}
    plots = [{"title": "S21 LogMag", "unit": "dB", "traces": ["|S21| (dB)"]},
             {"title": "S21 Phase", "unit": "°", "traces": ["Phase (°)"]}]
    marker_sets = None
    info_sets = {}

    @classmethod
    def run(cls, board, profile: SetupProfile, params: CwTimeParams,
            should_stop: Callable[[], bool] = lambda: False) -> Iterator[Update]:
        plan = plan_sweep(profile, params.freq_mhz, params.freq_mhz)
        cfg = {
            "cw_time": True,
            "outputs": outputs(board.soccfg, profile),
            "inputs": inputs(board.soccfg, profile),
            "freq": plan.if_start,
            "points": params.points,
            "gain": params.gain,
            "readout_length": params.readout_length_us,
            "spacing": _spacing(board.soccfg, inputs(board.soccfg, profile)[0], params.readout_length_us),
            "settle": params.settle_us,
        }
        program = _Program(board.soccfg, reps=params.averages, reps_innermost=True,
                           initial_delay=None, final_delay=None, cfg=cfg)
        x, x_axis = _time_axis(params.points, cfg["spacing"] * params.averages)

        # every sweep is kept for saving; np.savez stacks the list into (sweeps, points)
        sweeps, ends = [], []
        for i, iq in enumerate(board.run(program, None, should_stop, average=False), start=1):
            s21 = received_s21(iq, program, "probe", profile)
            sweeps.append(s21)
            ends.append(time.time())
            with np.errstate(divide="ignore"):  # no signal gives -inf dB, shown as a gap
                mag_db = 20 * np.log10(np.abs(s21))
            yield Update(i, None, x, {"|S21| (dB)": mag_db, "Phase (°)": np.degrees(np.angle(s21))},
                         raw={"s21": sweeps, "sweep_end_unix_s": ends}, x_axis=x_axis)


def _spacing(soccfg, ro: int, window_us: float) -> float:
    """Time from one window to the next, in µs: the window as the readout rounds it (its own clock),
    rounded up to whole tProc cycles, so windows never overlap and gaps stay under one cycle (1.6 ns)."""
    window = soccfg.cycles2us(soccfg.us2cycles(window_us, ro_ch=ro), ro_ch=ro)
    f_tproc = soccfg["tprocs"][0]["f_time"]
    return np.ceil(window * f_tproc - 1e-6) / f_tproc


def _time_axis(points: int, point_time_us: float):
    """Start time of each point, from the first point, in µs, ms or s depending on the sweep length."""
    t_us = np.arange(points) * point_time_us
    for unit, scale in (("µs", 1), ("ms", 1e3), ("s", 1e6)):
        if t_us[-1] < 1000 * scale or unit == "s":
            return t_us / scale, {"title": "Time", "unit": unit}
