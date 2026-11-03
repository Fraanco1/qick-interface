"""Resonator sweep: |S21| and phase against readout tone frequency."""
from collections.abc import Callable, Iterator
from typing import Literal

import numpy as np
from pydantic import BaseModel, Field
from qick.asm_v2 import AsmV2, AveragerProgramV2, QickSweep1D

from ..board import readout_channel
from ..frequency import plan_sweep, rf_from_if
from ..iq import TonesMixin, outputs
from ..profiles import SetupProfile
from .base import Update


class ResonatorSweepParams(BaseModel):
    rf_start_mhz: float = Field(title="Start", json_schema_extra={"unit": "MHz", "group": "Sweep"})
    rf_stop_mhz: float = Field(title="Stop", json_schema_extra={"unit": "MHz", "group": "Sweep"})
    points: int = Field(201, ge=2, le=10001, title="Points", json_schema_extra={"group": "Sweep"})
    gain: float = Field(0.5, ge=0, le=1, title="Gain", json_schema_extra={"group": "Power"})
    mode: Literal["pulsed", "cw"] = Field("pulsed", title="Mode", json_schema_extra={"group": "Timing"},
                                         description="CW keeps the tone on, like a PNA-X; pulsed sends one pulse per shot.")
    settle_us: float = Field(10.0, ge=0, le=1000, title="Settling time (CW)", json_schema_extra={"unit": "µs", "group": "Timing"},
                             description="Wait after each frequency step before measuring; a few times the resonator's 1/κ.")
    pulse_length_us: float = Field(2.0, gt=0, le=100, title="Pulse length (pulsed)", json_schema_extra={"unit": "µs", "group": "Timing"})
    readout_length_us: float = Field(1.5, gt=0, le=100, title="Readout window", json_schema_extra={"unit": "µs", "group": "Timing"})
    trigger_delay_us: float = Field(0.3, ge=0, title="Time of flight", json_schema_extra={"unit": "µs", "group": "Timing"})
    averages: int = Field(100, ge=1, title="Averages per round", json_schema_extra={"group": "Average"})
    rounds: int = Field(10, ge=1, title="Rounds", json_schema_extra={"group": "Average"})
    final_delay_us: float = Field(1.0, ge=0, title="Repetition delay (pulsed)", json_schema_extra={"unit": "µs", "group": "Timing"})


class _Program(TonesMixin, AveragerProgramV2):
    """Pulsed: one pulse per shot, the window opens after the time of flight.
    CW: each shot switches the continuously playing tone to the next frequency (it never stops),
    waits the settling time, then measures."""

    def _initialize(self, cfg):
        ro = cfg["ro"]
        self.declare_outputs(cfg)
        self.declare_readout(ch=ro, length=cfg["readout_length"])
        self.add_readoutconfig(ch=ro, name="ro", freq=cfg["freq"], gen_ch=cfg["outputs"][0].gen)
        push_ro = AsmV2()
        push_ro.send_readoutconfig(ch=ro, name="ro", t=0)
        self.add_loop("freq", cfg["points"], exec_before=push_ro)
        if cfg["cw"]:
            self.add_tone(cfg, "probe", freq=cfg["freq"], length=1.0, gain=cfg["gain"], mode="periodic")
        else:
            self.add_tone(cfg, "probe", freq=cfg["freq"], length=cfg["pulse_length"], gain=cfg["gain"])

    def _body(self, cfg):
        self.play_tone(cfg, "probe", t=0)
        window_start = cfg["settle"] + cfg["trigger_delay"] if cfg["cw"] else cfg["trigger_delay"]
        self.trigger(ros=[cfg["ro"]], pins=[0], t=window_start)
        if cfg["cw"]:
            self.delay_auto(t=0, gens=False)  # next frequency only after this window closes


class ResonatorSweep:
    name = "Resonator sweep"
    Params = ResonatorSweepParams
    x_axis = {"title": "Frequency", "unit": "MHz"}
    marker_sets = "readout_freq_mhz"  # chip parameter the marker can be stored as
    plots = [{"title": "S21 LogMag", "unit": "dB", "traces": ["|S21| (dB)"]},
             {"title": "S21 Phase", "unit": "°", "traces": ["Phase (°)"]}]
    info_sets = {}

    @staticmethod
    def if_axis(program) -> np.ndarray:
        """IF of each sweep point, in MHz, as rounded by QICK."""
        return program.get_pulse_param("probe", "freq", as_array=True)

    @classmethod
    def run(cls, board, profile: SetupProfile, params: ResonatorSweepParams,
            should_stop: Callable[[], bool] = lambda: False) -> Iterator[Update]:
        plan = plan_sweep(profile, params.rf_start_mhz, params.rf_stop_mhz)
        cfg = {
            "outputs": outputs(board.soccfg, profile),
            "ro": readout_channel(board.soccfg, profile.readout_adc),
            "freq": QickSweep1D("freq", plan.if_start, plan.if_stop),
            "points": params.points,
            "gain": params.gain,
            "pulse_length": params.pulse_length_us,
            "cw": params.mode == "cw",
            "settle": params.settle_us,
            "readout_length": params.readout_length_us,
            "trigger_delay": params.trigger_delay_us,
        }
        # in CW the tone never stops, so a repetition delay would only slow the sweep down
        final_delay = 0.05 if params.mode == "cw" else params.final_delay_us
        program = _Program(board.soccfg, reps=params.averages, final_delay=final_delay, cfg=cfg)
        if_mhz = cls.if_axis(program)
        rf = rf_from_if(profile, if_mhz)

        for i, iq in enumerate(board.run(program, params.rounds, should_stop), start=1):
            s21 = iq[0]
            with np.errstate(divide="ignore"):  # no signal gives -inf dB, shown as a gap
                mag_db = 20 * np.log10(np.abs(s21))
            yield Update(i, params.rounds, rf, {
                "|S21| (dB)": mag_db,
                "Phase (°)": np.degrees(_remove_electrical_delay(if_mhz, s21)),
            }, raw={"s21": s21, "if_mhz": if_mhz})


def _remove_electrical_delay(if_mhz, s21):
    """Phase with the best-fit cable delay and offset removed, wrapped to ±π."""
    phase = np.unwrap(np.angle(s21))
    slope, offset = np.polyfit(if_mhz, phase, 1)
    return np.angle(np.exp(1j * (phase - slope * if_mhz - offset)))
