from pathlib import Path

import numpy as np
import pytest
from qick import QickConfig

from qick_interface.board import FakeBoard
from qick_interface.measurements.resonator_sweep import ResonatorSweep
from qick_interface.power import FULL_SCALE_COUNTS, BoardCalibration, calibrate_adc_from_loopback, load_board, save_board

SOCCFG = QickConfig(str(Path(__file__).parent / "fixtures" / "soccfg_rfsoc4x2.json"))


def test_starts_from_the_data_sheets():
    cal = BoardCalibration()

    assert cal.dac_dbm("DAC_B", 550.0, 1.0) == pytest.approx(-1.0)
    assert cal.dac_dbm("DAC_B", 550.0, 0.5) == pytest.approx(-1.0 - 6.02, abs=0.01)
    assert cal.adc_dbm("ADC_D", 550.0, FULL_SCALE_COUNTS) == pytest.approx(3.0)
    assert cal.dac_full_scale_dbm["DAC_A"].source == "data sheet"


def test_interpolates_between_table_points_and_holds_beyond_the_ends():
    cal = BoardCalibration()

    assert cal.adc_dbm("ADC_D", 1500.0, FULL_SCALE_COUNTS) == pytest.approx(2.25)  # between 2.5 and 2.0
    assert cal.adc_dbm("ADC_D", 10.0, FULL_SCALE_COUNTS) == pytest.approx(3.0)


def test_a_full_scale_tone_is_the_full_scale_power_in_volts():
    cal = BoardCalibration()
    volts = FULL_SCALE_COUNTS * cal.adc_volts_per_count("ADC_D", 550.0)

    assert 10 * np.log10(volts ** 2 / (2 * 50) * 1000) == pytest.approx(3.0)


def test_the_loopback_finds_the_adc_scale_from_the_dacs():
    # the real ADC reads 2.5 dB less than the data sheet says, at every frequency
    cal = BoardCalibration()

    def loopback(program):
        f = ResonatorSweep.if_axis(program)
        dbm = cal.dac_dbm("DAC_B", f, program.get_pulse_param("probe", "gain"))
        true_full_scale = cal.dac_full_scale_dbm["DAC_B"].at(f) * 0 + 5.5  # 2.5 dB above the 3.0 dBm data sheet
        return [FULL_SCALE_COUNTS * 10 ** ((dbm - true_full_scale) / 20) + 0j]

    new = calibrate_adc_from_loopback(FakeBoard(SOCCFG, loopback), cal, "DAC_B", "ADC_D")

    assert new.adc_dbm("ADC_D", 550.0, FULL_SCALE_COUNTS) == pytest.approx(5.5, abs=0.01)
    assert new.adc_dbm("ADC_D", 1800.0, FULL_SCALE_COUNTS) == pytest.approx(5.5, abs=0.01)
    assert "loopback from DAC_B" in new.adc_full_scale_dbm["ADC_D"].source
    assert new.adc_full_scale_dbm["ADC_C"] == cal.adc_full_scale_dbm["ADC_C"]  # the others untouched


def test_says_so_when_the_loopback_is_not_cabled():
    with pytest.raises(ValueError, match="loopback cable"):
        calibrate_adc_from_loopback(FakeBoard(SOCCFG, lambda p: [np.full(21, 3 + 0j)]), BoardCalibration(), "DAC_B", "ADC_D")


def test_is_kept_in_the_profiles_folder(tmp_path):
    cal = BoardCalibration()
    cal.adc_full_scale_dbm["ADC_D"].points = [(100.0, 5.0), (2000.0, 4.0)]

    save_board(tmp_path, cal)

    assert load_board(tmp_path).adc_dbm("ADC_D", 100.0, FULL_SCALE_COUNTS) == pytest.approx(5.0)
    assert load_board(tmp_path / "empty").dac_full_scale_dbm["DAC_B"].source == "data sheet"


# ---- absolute traces from the measurements ----
from qick_interface.__main__ import simulated_chip  # noqa: E402
from qick_interface.measurements.cw_time import CwTime, CwTimeParams  # noqa: E402
from qick_interface.measurements.rabi import Rabi, RabiParams  # noqa: E402
from qick_interface.measurements.resonator_sweep import ResonatorSweepParams  # noqa: E402
from qick_interface.measurements.two_tone import TwoTone, TwoToneParams  # noqa: E402
from qick_interface.profiles import SetupProfile  # noqa: E402

LOOP = SetupProfile(chip="L", lo_mhz=None, readout_dac="DAC_B", readout_adc="ADC_D")
IQ_RETURN = LOOP.model_copy(update={"lo_mhz": 6000.0, "return_path": "iq"})
MEASURED = BoardCalibration(adc_full_scale_dbm={p: {"points": [(100, 4.0), (2000, 6.0)]} for p in ("ADC_B", "ADC_C", "ADC_D")})


def last_update(measurement, params, profile, first_only=False):
    board = FakeBoard(SOCCFG, simulated_chip)
    board.calibration = MEASURED
    updates = measurement.run(board, profile, params)
    return next(iter(updates)) if first_only else list(updates)[-1]


@pytest.mark.parametrize("measurement, params, if_mhz", [
    (ResonatorSweep, ResonatorSweepParams(rf_start_mhz=300.0, rf_stop_mhz=900.0, points=51, gain=0.4, rounds=1), None),
    (TwoTone, TwoToneParams(qubit_start_mhz=1000.0, qubit_stop_mhz=1200.0, points=21, readout_freq_mhz=700.0,
                            readout_gain=0.4, rounds=1), 700.0),
])
def test_magnitude_traces_also_come_in_dbm_at_the_adc(measurement, params, if_mhz):
    u = last_update(measurement, params, LOOP)
    f = u.x if if_mhz is None else if_mhz
    counts = 10 ** (u.traces["|S21| (dB)"] / 20) * 0.4  # |S21| is |I+jQ| / gain

    assert u.traces["Power (dBm)"] == pytest.approx(MEASURED.adc_dbm("ADC_D", f, counts), abs=0.01)


def test_cw_time_too():
    u = last_update(CwTime, CwTimeParams(freq_mhz=550.0, points=11, gain=0.4), LOOP, first_only=True)  # runs until Stop
    counts = 10 ** (u.traces["|S21| (dB)"] / 20) * 0.4

    assert u.traces["Power (dBm)"] == pytest.approx(MEASURED.adc_dbm("ADC_D", 550.0, counts), abs=0.01)


def test_on_the_iq_return_each_adc_sees_half_of_the_combined_signal():
    u = last_update(ResonatorSweep, ResonatorSweepParams(rf_start_mhz=6300.0, rf_stop_mhz=6900.0, points=51,
                                                         gain=0.4, rounds=1), IQ_RETURN)
    counts = 10 ** (u.traces["|S21| (dB)"] / 20) * 0.4 / 2

    assert u.traces["Power (dBm)"] == pytest.approx(MEASURED.adc_dbm("ADC_D", u.x - 6000.0, counts), abs=0.01)


def test_rabi_signal_also_comes_in_millivolts_at_the_adc():
    u = last_update(Rabi, RabiParams(qubit_freq_mhz=300.0, readout_freq_mhz=700.0, readout_gain=0.4, points=31,
                                     rounds=1), LOOP)
    mv_per_unit = 0.4 * MEASURED.adc_volts_per_count("ADC_D", 700.0) * 1e3

    assert u.traces["Signal (mV)"] == pytest.approx(u.traces["Signal"] * mv_per_unit, rel=1e-3)
    assert u.traces["Fit (mV)"] == pytest.approx(u.traces["Fit"] * mv_per_unit, rel=1e-3, nan_ok=True)


def test_the_loopback_cables_ripple_is_averaged_out():
    # a 1 m loopback cable between imperfect 50 Ω ports gives ±1 dB ripple with a 100 MHz period (bench, 2026-11-04);
    # it belongs to that cable, not to the ADC
    cal = BoardCalibration()

    def rippling_loopback(program):
        f = ResonatorSweep.if_axis(program)
        dbm = cal.dac_dbm("DAC_B", f, program.get_pulse_param("probe", "gain")) + np.sin(2 * np.pi * f / 100.0 + 1.0)  # its phase is the cable's
        return [FULL_SCALE_COUNTS * 10 ** ((dbm - 5.5) / 20) + 0j]

    new = calibrate_adc_from_loopback(FakeBoard(SOCCFG, rippling_loopback), cal, "DAC_B", "ADC_D")

    for f in (150.0, 575.0, 1234.0, 2050.0):
        assert new.adc_dbm("ADC_D", f, FULL_SCALE_COUNTS) == pytest.approx(5.5, abs=0.15)
