from pathlib import Path

import numpy as np
import pytest
from qick import QickConfig

from qick_interface.board import FakeBoard
from qick_interface.measurements.resonator_sweep import ResonatorSweep, ResonatorSweepParams
from qick_interface.profiles import SetupProfile
from qick_interface.tone import OutputTone, tone_program

SOCCFG = QickConfig(str(Path(__file__).parent / "fixtures" / "soccfg_rfsoc4x2.json"))
IQ = SetupProfile(chip="IQ", lo_mhz=None, output_path="iq", i_dac="DAC_A", q_dac="DAC_B")


def q_minus_i_deg(program, name, as_array=False):
    """Phase of the Q pulse relative to the I pulse, in (-180, 180]."""
    d = (program.get_pulse_param(name + "_q", "phase", as_array=as_array)
         - program.get_pulse_param(name, "phase", as_array=as_array))
    return (np.asarray(d) + 180) % 360 - 180


def wrapped(deg):
    return (np.asarray(deg) + 180) % 360 - 180


@pytest.mark.parametrize("sideband, sign", [("upper", 1), ("lower", -1)])
@pytest.mark.parametrize("delay_ps", [0.0, 3300.0])
def test_q_is_set_earlier_by_the_q_delay_so_i_and_q_leave_the_dacs_at_the_calibrated_phase(sideband, sign, delay_ps):
    # Q's DAC runs delay_ps ahead of I's, which adds 360°·f·delay to Q's phase; the app takes it off
    profile = IQ.model_copy(update={"sideband": sideband, "iq_delay_ps": delay_ps})

    program = tone_program(SOCCFG, profile, OutputTone(chip="IQ", rf_mhz=100.0, gain=0.3))

    assert q_minus_i_deg(program, "tone") == pytest.approx(wrapped(sign * 90 - 360 * 100e6 * delay_ps * 1e-12), abs=0.01)


def test_in_a_frequency_sweep_the_correction_follows_the_frequency():
    profile = IQ.model_copy(update={"iq_delay_ps": 3300.0})
    params = ResonatorSweepParams(rf_start_mhz=20.0, rf_stop_mhz=180.0, points=17)

    program, if_mhz, _ = ResonatorSweep.program(FakeBoard(SOCCFG, None), profile, params)

    expected = wrapped(90 - 360 * np.asarray(if_mhz) * 1e6 * 3300e-12)
    assert q_minus_i_deg(program, "probe", as_array=True) == pytest.approx(expected, abs=0.05)
