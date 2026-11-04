"""Resonator sweep: |S21| and phase against readout tone frequency."""
from collections.abc import Callable, Iterator
from typing import Literal

import numpy as np
from pydantic import BaseModel, Field
from qick.asm_v2 import AsmV2, AveragerProgramV2, QickSweep1D

from ..frequency import plan_sweep, rf_from_if
from ..iq import TonesMixin, inputs, outputs, send_readouts
from ..profiles import SetupProfile
from .base import ABSOLUTE_DB, Update, received_dbm, received_s21


class ResonatorSweepParams(BaseModel):
    rf_start_mhz: float = Field(title="Start", json_schema_extra={"unit": "MHz", "group": "Sweep"})
    rf_stop_mhz: float = Field(title="Stop", json_schema_extra={"unit": "MHz", "group": "Sweep"})
    points: int = Field(201, ge=2, le=10001, title="Points", json_schema_extra={"group": "Sweep"})
    gain: float = Field(0.5, ge=0, le=1, title="Gain", json_schema_extra={"group": "Power"})
    mode: Literal["pulsed", "cw"] = Field("pulsed", title="Mode", json_schema_extra={"group": "Timing"},
                                         description="CW keeps the tone on, like a PNA-X; pulsed sends one pulse per shot.")
    settle_us: float = Field(10.0, ge=0, le=1000, title="Settling time",
                             json_schema_extra={"unit": "µs", "group": "Timing", "shown_when": {"mode": "cw"}},
                             description="Wait after each frequency step before measuring; a few times the resonator's 1/κ.")
    pulse_length_us: float = Field(2.0, gt=0, le=100, title="Pulse length",
                                   json_schema_extra={"unit": "µs", "group": "Timing", "shown_when": {"mode": "pulsed"}})
    readout_length_us: float = Field(1.5, gt=0, le=100, title="Readout window", json_schema_extra={"unit": "µs", "group": "Timing"})
    averages: int = Field(100, ge=1, title="Averages per round", json_schema_extra={"group": "Average"})
    rounds: int = Field(10, ge=1, title="Rounds", json_schema_extra={"group": "Average"})
    final_delay_us: float = Field(1.0, ge=0, title="Repetition delay",
                                  json_schema_extra={"unit": "µs", "group": "Timing", "shown_when": {"mode": "pulsed"}})


class _Program(TonesMixin, AveragerProgramV2):
    """Pulsed: one pulse per shot, the window opens after the time of flight.
    CW: each shot switches the continuously playing tone to the next frequency (it never stops),
    waits the settling time, then measures."""

    def _initialize(self, cfg):
        self.declare_outputs(cfg)
        self.declare_inputs(cfg, length=cfg["readout_length"])
        self.add_readout(cfg, "ro", freq=cfg["freq"])
        push_ro = AsmV2()
        send_readouts(push_ro, cfg, "ro")
        self.add_loop("freq", cfg["points"], exec_before=push_ro)
        if cfg["cw"]:
            self.add_tone(cfg, "probe", freq=cfg["freq"], length=1.0, gain=cfg["gain"], mode="periodic")
        else:
            self.add_tone(cfg, "probe", freq=cfg["freq"], length=cfg["pulse_length"], gain=cfg["gain"])

    def _body(self, cfg):
        self.play_tone(cfg, "probe", t=0)
        window_start = cfg["settle"] + cfg["trigger_delay"] if cfg["cw"] else cfg["trigger_delay"]
        self.read(cfg, pins=[0], t=window_start)
        if cfg["cw"]:
            self.delay_auto(t=0, gens=False)  # next frequency only after this window closes


class ResonatorSweep:
    name = "Resonator sweep"
    Params = ResonatorSweepParams
    x_axis = {"title": "Frequency", "unit": "MHz"}
    marker_sets = "readout_freq_mhz"  # chip parameter the marker can be stored as
    drive_fields = {"gain": (("rf_start_mhz", "rf_stop_mhz"), "readout", "flat")}  # gain -> (frequency, line, shape)
    plots = [{"title": "S21 LogMag", "unit": "dB", "traces": ["|S21| (dB)"], "absolute": ABSOLUTE_DB},
             {"title": "S21 Phase", "unit": "°", "traces": ["Phase (°)"]}]
    info_sets = {}
    setup_sets = {"Electrical delay (ns)": "electrical_delay_ns"}  # fit result -> setup field
    setup_label = "electrical delay"

    @staticmethod
    def if_axis(program) -> np.ndarray:
        """IF of each sweep point, in MHz, as rounded by QICK."""
        return program.get_pulse_param("probe", "freq", as_array=True)

    @classmethod
    def program(cls, board, profile: SetupProfile, params: ResonatorSweepParams):
        """The compiled sweep program, with the IF and RF of each point as QICK rounded them."""
        plan = plan_sweep(profile, params.rf_start_mhz, params.rf_stop_mhz)
        cfg = {
            "outputs": outputs(board.soccfg, profile),
            "inputs": inputs(board.soccfg, profile),
            "freq": QickSweep1D("freq", plan.if_start, plan.if_stop),
            "points": params.points,
            "gain": params.gain,
            "pulse_length": params.pulse_length_us,
            "cw": params.mode == "cw",
            "settle": params.settle_us,
            "readout_length": params.readout_length_us,
            "trigger_delay": profile.time_of_flight_us,
        }
        # in CW the tone never stops, so a repetition delay would only slow the sweep down
        final_delay = 0.05 if params.mode == "cw" else params.final_delay_us
        program = _Program(board.soccfg, reps=params.averages, final_delay=final_delay, cfg=cfg)
        if_mhz = cls.if_axis(program)
        return program, if_mhz, rf_from_if(profile, if_mhz)

    @classmethod
    def run(cls, board, profile: SetupProfile, params: ResonatorSweepParams,
            should_stop: Callable[[], bool] = lambda: False) -> Iterator[Update]:
        program, if_mhz, rf = cls.program(board, profile, params)
        for i, iq in enumerate(board.run(program, params.rounds, should_stop), start=1):
            s21 = received_s21(iq, program, "probe", profile)
            with np.errstate(divide="ignore"):  # no signal gives -inf dB, shown as a gap
                mag_db = 20 * np.log10(np.abs(s21))
            fitted_ns = _fit_delay_ns(if_mhz, s21)
            delay_ns = fitted_ns if profile.electrical_delay_ns is None else profile.electrical_delay_ns
            yield Update(i, params.rounds, rf, {
                "|S21| (dB)": mag_db,
                "Power (dBm)": received_dbm(s21, program, "probe", profile, board.calibration),
                "Phase (°)": np.degrees(_remove_delay(if_mhz, s21, delay_ns)),
            }, raw={"s21": s21, "if_mhz": if_mhz}, info={"Electrical delay (ns)": fitted_ns})


def _fit_delay_ns(if_mhz, s21) -> float:
    """The sweep's own electrical delay: the slope of its unwrapped phase, −2π·f·τ. Reliable on a wide
    sweep with points closer than 1/(2τ) (2.3 MHz for the board's 216 ns), where a resonance is a small
    part of the data; on a narrow sweep the resonance's phase turn tilts it."""
    slope = np.polyfit(if_mhz, np.unwrap(np.angle(s21)), 1)[0]  # rad/MHz
    return -slope / (2 * np.pi) * 1e3


def _remove_delay(if_mhz, s21, delay_ns):
    """Phase with the delay and a constant offset removed, wrapped to ±π, like a PNA-X's Electrical Delay."""
    z = s21 * np.exp(2j * np.pi * np.asarray(if_mhz) * delay_ns * 1e-3)
    signal = np.abs(z) > 0  # points without signal don't count towards the offset
    offset = np.angle(np.mean(z[signal] / np.abs(z[signal]))) if signal.any() else 0.0
    return np.angle(z * np.exp(-1j * offset))
