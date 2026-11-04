"""Two-tone spectroscopy: sweep the qubit tone, read out at a fixed resonator frequency."""
from collections.abc import Callable, Iterator

import numpy as np
from pydantic import BaseModel, Field, ValidationInfo, field_validator
from pydantic_core import PydanticCustomError
from qick.asm_v2 import AveragerProgramV2, QickSweep1D

from ..frequency import drive_rf_from_if, plan_drive, plan_sweep
from ..iq import TonesMixin, control_outputs, inputs, outputs, send_readouts
from ..profiles import SetupProfile
from ..tone import LOOP_MAX
from .base import ABSOLUTE_DB, Update, received_dbm, received_s21


def _f(default=..., group=None, unit=None, chip=None, **kw):
    extra = {k: v for k, v in (("group", group), ("unit", unit), ("from_chip", chip)) if v}
    return Field(default, json_schema_extra=extra, **kw)


class TwoToneParams(BaseModel):
    # required for a run; the Output menu's sequence plays one frequency and does without them
    qubit_start_mhz: float | None = _f(None, group="Sweep", unit="MHz", title="Qubit start", validate_default=True)
    qubit_stop_mhz: float | None = _f(None, group="Sweep", unit="MHz", title="Qubit stop", validate_default=True)
    points: int = _f(201, group="Sweep", ge=2, le=10001, title="Points")
    qubit_gain: float = _f(0.1, group="Qubit", chip="qubit_gain", ge=0, le=1, title="Qubit gain")
    qubit_length_us: float = _f(10.0, group="Qubit", unit="µs", gt=0, le=100, title="Qubit pulse length")
    readout_freq_mhz: float = _f(group="Readout", unit="MHz", chip="readout_freq_mhz", title="Readout frequency")
    readout_gain: float = _f(0.5, group="Readout", chip="readout_gain", ge=0, le=1, title="Readout gain")
    readout_gap_us: float = _f(0.05, group="Readout", unit="µs", ge=0, le=100, title="Delay before readout",
                               description="From the end of the qubit pulse to the start of the readout pulse.")
    readout_pulse_us: float = _f(2.0, group="Readout", unit="µs", gt=0, le=100, title="Readout pulse length")
    readout_length_us: float = _f(1.5, group="Readout", unit="µs", gt=0, le=100, title="Readout window")
    averages: int = _f(100, group="Average", ge=1, title="Averages per round")
    rounds: int = _f(10, group="Average", ge=1, title="Rounds")
    final_delay_us: float = _f(500.0, group="Average", unit="µs", ge=0, title="Repetition delay",
                              description="Wait between shots so the qubit relaxes: about 5×T1.")
    scope_qubit_freq_mhz: float | None = _f(None, group="Output", unit="MHz", chip="qubit_freq_mhz",
                                            title="Qubit frequency",
                                            description="The one qubit frequency the sequence plays (RF).")

    @field_validator("qubit_start_mhz", "qubit_stop_mhz")
    @classmethod
    def _needed_for_a_sweep(cls, v, info: ValidationInfo):
        if v is None and not (info.context or {}).get("sequence"):
            raise PydanticCustomError("missing", "Field required")
        return v


class _Program(TonesMixin, AveragerProgramV2):
    def _initialize(self, cfg):
        self.declare_outputs(cfg)
        self.declare_inputs(cfg, length=cfg["readout_length"])
        self.add_readout(cfg, "ro", freq=cfg["readout_freq"])
        self.add_loop("freq", cfg["points"])
        self.add_tone(cfg, "qubit", freq=cfg["qubit_freq"], length=cfg["qubit_length"], gain=cfg["qubit_gain"],
                      line="control")
        self.add_tone(cfg, "readout", freq=cfg["readout_freq"], length=cfg["readout_pulse"],
                      gain=cfg["readout_gain"])

    def _body(self, cfg):
        send_readouts(self, cfg, "ro")
        self.play_tone(cfg, "qubit", t=0)
        if cfg["scope"]:  # PMOD0_0 is high while the qubit pulse plays
            self.trigger(pins=[0], t=0, width=cfg["qubit_length"])
        self.delay_auto(t=cfg["readout_gap"])  # from the end of the qubit pulse
        self.play_tone(cfg, "readout", t=0)
        self.read(cfg, pins=None if cfg["scope"] else [0], t=cfg["trigger_delay"])


class TwoTone:
    name = "Two-tone spectroscopy"
    Params = TwoToneParams
    x_axis = {"title": "Qubit frequency", "unit": "MHz"}
    marker_sets = "qubit_freq_mhz"  # chip parameter the marker can be stored as
    drive_fields = {"qubit_gain": (("qubit_start_mhz", "qubit_stop_mhz"), "qubit", "flat"),
                    "readout_gain": ("readout_freq_mhz", "readout", "flat")}
    plots = [{"title": "S21 LogMag", "unit": "dB", "traces": ["|S21| (dB)"], "absolute": ABSOLUTE_DB},
             {"title": "S21 Phase", "unit": "°", "traces": ["Phase (°)"]}]
    info_sets = {}

    @staticmethod
    def qubit_if_axis(program) -> np.ndarray:
        """IF of the qubit tone at each sweep point, in MHz, as rounded by QICK."""
        return program.get_pulse_param("qubit", "freq", as_array=True)

    @staticmethod
    def _program(soccfg, profile, params, qubit_start_mhz, qubit_stop_mhz, points, reps, scope=False):
        qubit = plan_drive(profile, qubit_start_mhz, qubit_stop_mhz)
        readout = plan_sweep(profile, params.readout_freq_mhz, params.readout_freq_mhz)
        qubit_freq = qubit.if_start if scope else QickSweep1D("freq", qubit.if_start, qubit.if_stop)
        return _Program(soccfg, reps=reps, final_delay=params.final_delay_us, cfg={
            "outputs": outputs(soccfg, profile),
            "control": control_outputs(soccfg, profile),
            "inputs": inputs(soccfg, profile),
            "qubit_freq": qubit_freq,
            "readout_freq": readout.if_start,
            "points": points,
            "qubit_gain": params.qubit_gain,
            "qubit_length": params.qubit_length_us,
            "readout_gain": params.readout_gain,
            "readout_gap": params.readout_gap_us,
            "readout_pulse": params.readout_pulse_us,
            "readout_length": params.readout_length_us,
            "trigger_delay": profile.time_of_flight_us,
            "scope": scope,
        })

    @classmethod
    def sequence(cls, soccfg, profile: SetupProfile, params: TwoToneParams):
        """One shot at the Output menu's qubit frequency, repeated until silenced, for an oscilloscope."""
        if params.scope_qubit_freq_mhz is None:
            raise ValueError("Enter the Qubit frequency in the Output menu.")
        f = params.scope_qubit_freq_mhz
        return cls._program(soccfg, profile, params, f, f, points=LOOP_MAX, reps=LOOP_MAX, scope=True)

    @classmethod
    def run(cls, board, profile: SetupProfile, params: TwoToneParams,
            should_stop: Callable[[], bool] = lambda: False) -> Iterator[Update]:
        program = cls._program(board.soccfg, profile, params, params.qubit_start_mhz, params.qubit_stop_mhz,
                               points=params.points, reps=params.averages)
        qubit_if = cls.qubit_if_axis(program)
        rf = drive_rf_from_if(profile, qubit_if)

        for i, iq in enumerate(board.run(program, params.rounds, should_stop), start=1):
            s21 = received_s21(iq, program, "readout", profile)
            with np.errstate(divide="ignore"):  # no signal gives -inf dB, shown as a gap
                mag_db = 20 * np.log10(np.abs(s21))
            # phase relative to the sweep's mean, so the qubit response stands out
            phase = np.degrees(np.angle(s21 * np.exp(-1j * np.angle(np.mean(s21)))))
            yield Update(i, params.rounds, rf, {"|S21| (dB)": mag_db, "Phase (°)": phase,
                                                "Power (dBm)": received_dbm(s21, program, "readout", profile,
                                                                            board.calibration)},
                         raw={"s21": s21, "qubit_if_mhz": qubit_if})
