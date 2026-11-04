"""Output tone: a continuous tone on the chip's output path, for the I/Q calibration with a spectrum
analyzer. One periodic pulse that keeps playing until silenced. (Pulsed measurements check their
pulses on a scope with their own sequence, e.g. Rabi.sequence.)
"""
from pydantic import BaseModel, Field
from qick.asm_v2 import AveragerProgramV2

from .frequency import plan_sweep
from .iq import TonesMixin, inputs, outputs
from .profiles import SetupProfile

LOOP_MAX = 2**23 - 1  # largest tProc loop count; two nested loops of it run for years


class OutputTone(BaseModel):
    chip: str
    rf_mhz: float
    gain: float = Field(0.3, ge=0, le=1)
    # I/Q calibration being tuned; None uses the values saved in the setup profile
    iq_phase_deg: float | None = Field(None, ge=0, le=180)
    iq_gain_ratio: float | None = Field(None, gt=0, le=2)


class _ToneProgram(TonesMixin, AveragerProgramV2):
    def _initialize(self, cfg):
        self.declare_outputs(cfg)
        self.add_tone(cfg, "tone", freq=cfg["freq"], length=1.0, gain=cfg["gain"], mode="periodic")

    def _body(self, cfg):
        self.play_tone(cfg, "tone", t=0)


def tone_program(soccfg, profile: SetupProfile, tone: OutputTone):
    overrides = {k: v for k, v in (("iq_phase_deg", tone.iq_phase_deg), ("iq_gain_ratio", tone.iq_gain_ratio))
                 if v is not None}
    tuned = profile.model_copy(update=overrides)
    plan = plan_sweep(tuned, tone.rf_mhz, tone.rf_mhz, drive_only=True)
    cfg = {"outputs": outputs(soccfg, tuned), "inputs": inputs(soccfg, profile), "freq": plan.if_start, "gain": tone.gain}
    return _ToneProgram(soccfg, reps=1, final_delay=1.0, cfg=cfg)
