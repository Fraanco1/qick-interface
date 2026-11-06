from pathlib import Path

import numpy as np
import pytest
from qick import QickConfig

from qick_interface.board import FakeBoard
from qick_interface.fake_analyzer import FakeAnalyzer
from qick_interface.measurements.resonator_sweep import ResonatorSweep
from qick_interface.power import (FULL_SCALE_COUNTS, BoardCalibration, CalibrationLibrary, Table,
                                  calibrate_adc_from_loopback, calibrate_dac_with_analyzer, load_board, save_board)

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
    mv = FULL_SCALE_COUNTS * cal.adc_linear_per_count("ADC_D", 550.0)

    assert 10 * np.log10((mv / 1e3) ** 2 / (2 * 50) * 1000) == pytest.approx(3.0)
    assert cal.adc_units("ADC_D") == ("dBm", "mV")


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
    library, _ = CalibrationLibrary().add("ADC_D", Table(points=[(100.0, 5.0), (2000.0, 4.0)], source="loopback"))

    save_board(tmp_path, library)

    assert load_board(tmp_path).resolve({}).adc_dbm("ADC_D", 100.0, FULL_SCALE_COUNTS) == pytest.approx(5.0)
    assert load_board(tmp_path / "empty").resolve({}).dac_full_scale_dbm["DAC_B"].source == "data sheet"


# ---- the library of tables: every port keeps all of its calibrations, a chip's setup picks one per port ----
PXA_OLD = Table(points=[(100.0, -2.0)], source="N9032B, cable 0.5 dB, 2026-11-05")
PXA_NEW = Table(points=[(100.0, -1.5)], source="N9032B, cable 0.5 dB, 2026-11-06")


def test_a_port_with_no_choice_uses_its_newest_table_or_the_data_sheet():
    library = CalibrationLibrary()
    library, _ = library.add("DAC_A", PXA_OLD)
    library, _ = library.add("DAC_A", PXA_NEW)

    cal = library.resolve({})

    assert cal.dac_full_scale_dbm["DAC_A"].source == PXA_NEW.source
    assert cal.dac_full_scale_dbm["DAC_B"].source == "data sheet"


def test_a_chip_can_pick_an_older_table_or_the_data_sheet():
    library, _ = CalibrationLibrary().add("DAC_A", PXA_OLD)
    library, _ = library.add("DAC_A", PXA_NEW)

    assert library.resolve({"DAC_A": PXA_OLD.source}).dac_dbm("DAC_A", 100.0, 1.0) == pytest.approx(-2.0)
    assert library.resolve({"DAC_A": "data sheet"}).dac_dbm("DAC_A", 550.0, 1.0) == pytest.approx(-1.0)


def test_no_calibration_gives_powers_relative_to_full_scale():
    cal = CalibrationLibrary().resolve({"DAC_B": "none", "ADC_D": "none"})

    assert cal.dac_dbm("DAC_B", 1234.0, 0.5) == pytest.approx(-6.02, abs=0.01)  # dBFS: gain 1 is 0
    assert cal.adc_dbm("ADC_D", 1234.0, FULL_SCALE_COUNTS) == pytest.approx(0.0)
    assert cal.adc_units("ADC_D") == ("dBFS", "% FS")
    assert FULL_SCALE_COUNTS * cal.adc_linear_per_count("ADC_D", 1234.0) == pytest.approx(100.0)
    assert cal.dac_full_scale_dbm["DAC_B"].unit == "dBFS"
    assert cal.adc_units("ADC_C") == ("dBm", "mV")  # the others keep theirs


def test_a_choice_that_is_gone_says_which_port():
    with pytest.raises(ValueError, match="ADC_D"):
        CalibrationLibrary().resolve({"ADC_D": "loopback, deleted since"})


def test_a_new_table_never_replaces_an_older_one_with_the_same_name():
    library, first = CalibrationLibrary().add("DAC_A", PXA_NEW)
    library, second = library.add("DAC_A", PXA_NEW.model_copy(update={"points": [(100.0, -1.4)]}))

    assert first == PXA_NEW.source and second == f"{PXA_NEW.source} (2)"
    assert [t.source for t in library.dac["DAC_A"]] == [first, second]


def test_a_table_cannot_take_a_built_in_name():
    with pytest.raises(ValueError):
        CalibrationLibrary(adc={"ADC_D": [Table(points=[(100.0, 5.0)], source="none")]})


def test_the_one_table_per_port_file_becomes_a_library(tmp_path):
    # the format before 2026-11-06: one table per port, the data sheet's included
    old = BoardCalibration()
    old.adc_full_scale_dbm["ADC_D"] = Table(points=[(100.0, 5.5)], source="loopback from DAC_A, 2026-11-06")
    (tmp_path / "board").mkdir()
    (tmp_path / "board" / "calibration.json").write_text(old.model_dump_json())

    library = load_board(tmp_path)

    assert [t.source for t in library.adc["ADC_D"]] == ["loopback from DAC_A, 2026-11-06"]
    assert library.dac["DAC_A"] == [] and library.adc["ADC_B"] == []  # the data sheet is built in


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
    mv_per_unit = 0.4 * MEASURED.adc_linear_per_count("ADC_D", 700.0)

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


def dac_a_output(f_mhz):
    """A made-up DAC_A: −0.5 dBm at gain 1, rolling off 1 dB per GHz."""
    return -0.5 - f_mhz / 1000


def test_the_analyzer_fills_the_dacs_table_every_50_mhz_with_the_cable_loss_added_back():
    board = FakeBoard(SOCCFG, lambda program: [])
    analyzer = FakeAnalyzer(board, {"DAC_A": dac_a_output}, cable_loss_db=0.7)

    new = calibrate_dac_with_analyzer(board, analyzer, BoardCalibration(), "DAC_A", cable_loss_db=0.7)

    table = new.dac_full_scale_dbm["DAC_A"]
    f, dbm = np.array(table.points).T
    assert f[0] == 50 and f[-1] == 4900 and np.all(np.diff(f) == 50)
    assert dbm == pytest.approx(dac_a_output(f), abs=0.01)  # at gain 1, at the DAC's SMA
    assert analyzer.model in table.source and "0.7 dB" in table.source
    assert new.dac_full_scale_dbm["DAC_B"].source == "data sheet"  # the other DAC is untouched
    assert board.playing is None  # nothing left playing


def test_says_so_when_the_analyzer_sees_nothing_from_the_dac():
    board = FakeBoard(SOCCFG, lambda program: [])
    analyzer = FakeAnalyzer(board, {"DAC_B": dac_a_output})  # the cable is on DAC_B

    with pytest.raises(ValueError, match="check the cable"):
        calibrate_dac_with_analyzer(board, analyzer, BoardCalibration(), "DAC_A", cable_loss_db=0.0)
    assert board.playing is None
