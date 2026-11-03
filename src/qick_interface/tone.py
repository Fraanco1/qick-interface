"""Output tone: a tone on the chip's output path for checking the setup with an oscilloscope or
spectrum analyzer, like the CW source of a PNA-X. Also used for I/Q calibration.

Continuous: one periodic pulse that keeps playing until silenced.
Pulsed: a pulse train (pulse length, period), with a marker on PMOD0_0 at each pulse start
for triggering the oscilloscope; it runs until silenced.
"""
from typing import Literal

from pydantic import BaseModel, Field, model_validator
from qick.asm_v2 import AveragerProgramV2

from .board import readout_channel
from .frequency import plan_sweep
from .iq import TonesMixin, outputs
from .profiles import SetupProfile

LOOP_MAX = 2**23 - 1  # largest tProc loop count; two nested loops run for years


class OutputTone(BaseModel):
    chip: str
    rf_mhz: float
    gain: float = Field(0.3, ge=0, le=1)
    mode: Literal["continuous", "pulsed"] = "continuous"
    pulse_length_us: float = Field(1.0, gt=0, le=100)
    period_us: float = Field(10.0, gt=0)
    # I/Q calibration being tuned; None uses the values saved in the setup profile
    iq_phase_deg: float | None = Field(None, ge=0, le=180)
    iq_gain_ratio: float | None = Field(None, gt=0, le=2)

    @model_validator(mode="after")
    def _period_fits_the_pulse(self):
        if self.mode == "pulsed" and self.period_us <= self.pulse_length_us:
            raise ValueError("The period must be longer than the pulse.")
        return self


class _ToneProgram(TonesMixin, AveragerProgramV2):
    def _initialize(self, cfg):
        self.declare_outputs(cfg)
        if cfg["pulsed"]:
            self.add_loop("train", LOOP_MAX)
            self.add_tone(cfg, "tone", freq=cfg["freq"], length=cfg["pulse_length"], gain=cfg["gain"], mode="oneshot")
        else:
            self.add_tone(cfg, "tone", freq=cfg["freq"], length=1.0, gain=cfg["gain"], mode="periodic")

    def _body(self, cfg):
        self.play_tone(cfg, "tone", t=0)
        if cfg["pulsed"]:
            self.trigger(pins=[0], t=0)  # PMOD0_0 marks each pulse for the oscilloscope


def tone_program(soccfg, profile: SetupProfile, tone: OutputTone):
    overrides = {k: v for k, v in (("iq_phase_deg", tone.iq_phase_deg), ("iq_gain_ratio", tone.iq_gain_ratio))
                 if v is not None}
    tuned = profile.model_copy(update=overrides)
    plan = plan_sweep(tuned, tone.rf_mhz, tone.rf_mhz, drive_only=True)
    pulsed = tone.mode == "pulsed"
    cfg = {"outputs": outputs(soccfg, tuned), "ro": readout_channel(soccfg, profile.readout_adc),
           "freq": plan.if_start, "gain": tone.gain, "pulsed": pulsed, "pulse_length": tone.pulse_length_us}
    if pulsed:
        return _ToneProgram(soccfg, reps=LOOP_MAX, final_delay=tone.period_us - tone.pulse_length_us, cfg=cfg)
    return _ToneProgram(soccfg, reps=1, final_delay=1.0, cfg=cfg)
