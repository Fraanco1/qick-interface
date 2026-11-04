from pathlib import Path

import numpy as np
import pytest
from qick import QickConfig

from qick_interface.board import FakeBoard
from qick_interface.measurements.resonator_sweep import ResonatorSweep, ResonatorSweepParams
from qick_interface.measurements.rx_iq_cal import RxIqCal
from qick_interface.profiles import SetupProfile

SOCCFG = QickConfig(str(Path(__file__).parent / "fixtures" / "soccfg_rfsoc4x2.json"))

# The imbalance of the simulated return path: Q/I gain, phase offset, and the delay between the I and Q
# cables (about 1 cm of coax), so the phase error grows with the IF.
GAIN, PHASE_DEG, DELAY_PS = 0.9, 5.0, 48.0


def iq_setup(sideband="upper", calibrated=True):
    rx = dict(rx_gain_ratio=GAIN, rx_phase_deg=PHASE_DEG, rx_delay_ps=DELAY_PS) if calibrated else {}
    return SetupProfile(chip="Transmon A", chip_type="transmon", lo_mhz=6000.0 if sideband == "upper" else 6300.0,
                        sideband=sideband, return_path="iq", i_adc="ADC_D", q_adc="ADC_C", **rx)


def chip(rf):
    return 1 - 0.9 / (1 + 2j * (rf - 6150.0) / 2.0)


def iq_mixer_return(profile):
    """What the I and Q readouts see through an imbalanced I/Q mixer: on the upper sideband
    Y_Q = −j·r·Y_I; on the lower one the mixer delivers the conjugate and Y_Q = +j·r·Y_I."""
    def simulate(program):
        f = ResonatorSweep.if_axis(program)
        r = GAIN * np.exp(1j * (np.radians(PHASE_DEG) + 2 * np.pi * f * DELAY_PS * 1e-6))
        if profile.sideband == "upper":
            y_i = chip(profile.lo_mhz + f) / 2
            return [y_i, -1j * r * y_i]
        y_i = np.conj(chip(profile.lo_mhz - f)) / 2
        return [y_i, 1j * r * y_i]
    return simulate


def sweep(profile, simulate, **params):
    defaults = dict(rf_start_mhz=6100.0, rf_stop_mhz=6200.0, points=201, gain=1.0, rounds=1)
    return list(ResonatorSweep.run(FakeBoard(SOCCFG, simulate), profile,
                                   ResonatorSweepParams(**{**defaults, **params})))[-1]


@pytest.mark.parametrize("sideband", ["upper", "lower"])
def test_iq_return_combines_both_inputs_into_the_chip_response(sideband):
    profile = iq_setup(sideband)
    u = sweep(profile, iq_mixer_return(profile))

    assert u.raw["s21"] == pytest.approx(chip(u.x), abs=1e-6)


def test_without_calibration_the_imbalance_distorts_the_response():
    calibrated, uncalibrated = iq_setup(), iq_setup(calibrated=False)
    u = sweep(uncalibrated, iq_mixer_return(calibrated))

    assert np.max(np.abs(u.raw["s21"] - chip(u.x))) > 0.05


def test_iq_return_triggers_the_i_and_q_readouts_together():
    programs = []

    def capture(program):
        programs.append(program)
        return iq_mixer_return(iq_setup())(program)

    sweep(iq_setup(), capture)

    assert list(programs[0].ro_chs) == [0, 1]  # ADC_D, ADC_C


def test_calibration_measures_the_imbalance_even_across_a_resonance():
    profile = iq_setup(calibrated=False)
    params = RxIqCal.Params(rf_start_mhz=6100.0, rf_stop_mhz=6200.0, points=41, rounds=1)

    u = list(RxIqCal.run(FakeBoard(SOCCFG, iq_mixer_return(profile)), profile, params))[-1]

    assert u.info["Q/I gain"] == pytest.approx(GAIN, rel=1e-4)
    assert u.info["Q phase (°)"] == pytest.approx(PHASE_DEG, abs=0.01)
    assert u.info["I/Q delay (ps)"] == pytest.approx(DELAY_PS, abs=0.5)
    assert u.info["Image rejection (dB)"] > 40


def test_calibration_needs_an_iq_return_path():
    real = SetupProfile(chip="Fluxonium", chip_type="fluxonium", lo_mhz=6000.0)
    params = RxIqCal.Params(rf_start_mhz=6100.0, rf_stop_mhz=6200.0, rounds=1)

    with pytest.raises(ValueError, match="Return path"):
        list(RxIqCal.run(FakeBoard(SOCCFG, lambda p: [np.ones(41)]), real, params))
