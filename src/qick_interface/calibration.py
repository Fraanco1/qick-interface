"""I/Q calibration tone: a continuous tone on the I/Q pair, tuned while watching a spectrum analyzer."""
from pydantic import BaseModel, Field
from qick.asm_v2 import AveragerProgramV2

from .board import readout_channel
from .frequency import FrequencyError, plan_sweep
from .iq import iq_output
from .profiles import SetupProfile


class IqTone(BaseModel):
    chip: str
    rf_mhz: float
    gain: float = Field(0.3, ge=0, le=1)
    iq_phase_deg: float = Field(90.0, ge=0, le=180)
    iq_gain_ratio: float = Field(1.0, gt=0, le=2)


class _ToneProgram(AveragerProgramV2):
    def _initialize(self, cfg):
        for name, gen, phase, gain in (("tone_i", cfg["gen"], 0, cfg["gain"]),
                                       ("tone_q", cfg["q_gen"], cfg["q_phase"], cfg["q_gain"])):
            self.declare_gen(ch=gen, nqz=1)
            # matched to the same readout so I and Q stay phase-locked
            self.add_pulse(ch=gen, name=name, ro_ch=cfg["ro"], style="const", mode="periodic",
                           freq=cfg["freq"], length=1.0, phase=phase, gain=gain)

    def _body(self, cfg):
        self.pulse(ch=cfg["gen"], name="tone_i", t=0)
        self.pulse(ch=cfg["q_gen"], name="tone_q", t=0)


def iq_tone_program(soccfg, profile: SetupProfile, tone: IqTone):
    if profile.output_path != "iq":
        raise FrequencyError(f"{profile.chip} uses the real output path; I/Q calibration needs the I/Q path.")
    tuned = profile.model_copy(update={"iq_phase_deg": tone.iq_phase_deg, "iq_gain_ratio": tone.iq_gain_ratio})
    plan = plan_sweep(tuned, tone.rf_mhz, tone.rf_mhz)
    cfg = {"ro": readout_channel(soccfg, profile.readout_adc), "freq": plan.if_start,
           **iq_output(soccfg, tuned, tone.gain)}
    return _ToneProgram(soccfg, reps=1, final_delay=1.0, cfg=cfg)
