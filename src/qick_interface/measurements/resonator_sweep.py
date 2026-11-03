"""Resonator sweep: |S21| and phase against readout tone frequency."""
from collections.abc import Callable, Iterator

import numpy as np
from pydantic import BaseModel, Field
from qick.asm_v2 import AsmV2, AveragerProgramV2, QickSweep1D

from ..board import gen_channel, readout_channel
from ..frequency import plan_sweep, rf_from_if
from ..profiles import SetupProfile
from .base import Update


class ResonatorSweepParams(BaseModel):
    rf_start_mhz: float = Field(title="Start", json_schema_extra={"unit": "MHz", "group": "Sweep"})
    rf_stop_mhz: float = Field(title="Stop", json_schema_extra={"unit": "MHz", "group": "Sweep"})
    points: int = Field(201, ge=2, le=10001, title="Points", json_schema_extra={"group": "Sweep"})
    gain: float = Field(0.5, ge=0, le=1, title="Gain", json_schema_extra={"group": "Power"})
    pulse_length_us: float = Field(2.0, gt=0, le=100, title="Pulse length", json_schema_extra={"unit": "µs", "group": "Timing"})
    readout_length_us: float = Field(1.5, gt=0, le=29, title="Readout window", json_schema_extra={"unit": "µs", "group": "Timing"})
    trigger_delay_us: float = Field(0.3, ge=0, title="Time of flight", json_schema_extra={"unit": "µs", "group": "Timing"})
    averages: int = Field(100, ge=1, title="Averages per round", json_schema_extra={"group": "Average"})
    rounds: int = Field(10, ge=1, title="Rounds", json_schema_extra={"group": "Average"})
    final_delay_us: float = Field(1.0, ge=0, title="Repetition delay", json_schema_extra={"unit": "µs", "group": "Timing"})


class _Program(AveragerProgramV2):
    def _initialize(self, cfg):
        gen, ro = cfg["gen"], cfg["ro"]
        self.declare_gen(ch=gen, nqz=1)
        self.declare_readout(ch=ro, length=cfg["readout_length"])
        self.add_readoutconfig(ch=ro, name="ro", freq=cfg["freq"], gen_ch=gen)
        push_ro = AsmV2()
        push_ro.send_readoutconfig(ch=ro, name="ro", t=0)
        self.add_loop("freq", cfg["points"], exec_before=push_ro)
        self.add_pulse(ch=gen, name="probe", ro_ch=ro, style="const", freq=cfg["freq"],
                       length=cfg["pulse_length"], phase=0, gain=cfg["gain"])
        if "q_gen" in cfg:  # I/Q output: same tone on a second DAC, phase-locked through ro_ch
            self.declare_gen(ch=cfg["q_gen"], nqz=1)
            self.add_pulse(ch=cfg["q_gen"], name="probe_q", ro_ch=ro, style="const", freq=cfg["freq"],
                           length=cfg["pulse_length"], phase=cfg["q_phase"], gain=cfg["q_gain"])

    def _body(self, cfg):
        self.pulse(ch=cfg["gen"], name="probe", t=0)
        if "q_gen" in cfg:
            self.pulse(ch=cfg["q_gen"], name="probe_q", t=0)
        self.trigger(ros=[cfg["ro"]], pins=[0], t=cfg["trigger_delay"])


class ResonatorSweep:
    name = "Resonator sweep"
    Params = ResonatorSweepParams

    @staticmethod
    def if_axis(program) -> np.ndarray:
        """IF of each sweep point, in MHz, as rounded by QICK."""
        return program.get_pulse_param("probe", "freq", as_array=True)

    @classmethod
    def run(cls, board, profile: SetupProfile, params: ResonatorSweepParams,
            should_stop: Callable[[], bool] = lambda: False) -> Iterator[Update]:
        plan = plan_sweep(profile, params.rf_start_mhz, params.rf_stop_mhz)
        cfg = {
            "gen": gen_channel(board.soccfg, profile.readout_dac),
            "ro": readout_channel(board.soccfg, profile.readout_adc),
            "freq": QickSweep1D("freq", plan.if_start, plan.if_stop),
            "points": params.points,
            "gain": params.gain,
            "pulse_length": params.pulse_length_us,
            "readout_length": params.readout_length_us,
            "trigger_delay": params.trigger_delay_us,
        }
        if profile.output_path == "iq":
            cfg.update(_iq_output(board.soccfg, profile, params.gain))
        program = _Program(board.soccfg, reps=params.averages, final_delay=params.final_delay_us, cfg=cfg)
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


def _iq_output(soccfg, profile: SetupProfile, gain: float) -> dict:
    """Gens, gains and Q phase for the I/Q output path. The larger of I and Q gets `gain`;
    the sign of the Q phase picks the sideband."""
    i_gain = gain / max(1.0, profile.iq_gain_ratio)
    sign = 1 if profile.sideband == "upper" else -1
    return {"gen": gen_channel(soccfg, profile.i_dac), "gain": i_gain,
            "q_gen": gen_channel(soccfg, profile.q_dac), "q_gain": i_gain * profile.iq_gain_ratio,
            "q_phase": sign * profile.iq_phase_deg}


def _remove_electrical_delay(if_mhz, s21):
    """Phase with the best-fit cable delay and offset removed, wrapped to ±π."""
    phase = np.unwrap(np.angle(s21))
    slope, offset = np.polyfit(if_mhz, phase, 1)
    return np.angle(np.exp(1j * (phase - slope * if_mhz - offset)))
