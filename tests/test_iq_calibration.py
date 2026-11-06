"""The TX I/Q calibration on the signal analyzer: the Q delay, then the Q phase and gain against IF."""
from pathlib import Path

import numpy as np
import pytest
from qick import QickConfig

from qick_interface.board import FakeBoard
from qick_interface.fake_analyzer import FakeIqMixer
from qick_interface.iq_calibration import calibrate
from qick_interface.profiles import SetupProfile
from qick_interface.tone import OutputTone, tone_program

SOCCFG = QickConfig(str(Path(__file__).parent / "fixtures" / "soccfg_rfsoc4x2.json"))
TRANSMON = SetupProfile(chip="T", lo_mhz=5000.0, output_path="iq", i_dac="DAC_A", q_dac="DAC_B",
                        iq_delay_ps=0.0)
# like the bench's MMIQ-0416LS: a few degrees of phase error and a gain imbalance, both changing with IF
MIXER = dict(phase_error_deg=lambda f: -4.0 + 1.5 * np.sin(f / 700.0), gain_error=lambda f: 1.0 + 0.08 * (f / 3000) ** 2)
IFS = dict(if_start_mhz=50.0, if_stop_mhz=3000.0, if_step_mhz=250.0)


def bench(profile, q_lead_ps):
    board = FakeBoard(SOCCFG, lambda program: [])
    return board, FakeIqMixer(board, profile.lo_mhz, q_lead_ps=q_lead_ps, **MIXER)


def image_below_wanted_db(board, analyzer, profile, if_mhz):
    sign = 1 if profile.sideband == "upper" else -1
    rf = profile.lo_mhz + sign * if_mhz
    board.play(tone_program(SOCCFG, profile, OutputTone(chip=profile.chip, rf_mhz=rf, gain=0.5)))
    return analyzer.peak_dbm(rf) - analyzer.peak_dbm(profile.lo_mhz - sign * if_mhz)


@pytest.mark.parametrize("q_lead_ps", [1500.0, 3300.0, -800.0])
@pytest.mark.parametrize("sideband", ["upper", "lower"])
def test_finds_the_q_delay_and_a_table_that_suppresses_the_image_at_every_if(q_lead_ps, sideband):
    profile = TRANSMON.model_copy(update={"sideband": sideband})
    board, analyzer = bench(profile, q_lead_ps)

    result = calibrate(board, analyzer, profile, **IFS)

    assert board.playing is None  # nothing left playing
    assert result["iq_delay_ps"] == pytest.approx(q_lead_ps, abs=5)
    calibrated = profile.model_copy(update={k: result[k] for k in ("iq_delay_ps", "iq_table")})
    for f in (50.0, 175.0, 640.0, 1000.0, 2222.0, 3000.0):  # between table points too
        assert image_below_wanted_db(board, analyzer, calibrated, f) > 50


def test_reports_the_suppression_it_reached_at_each_if():
    board, analyzer = bench(TRANSMON, 1500.0)

    result = calibrate(board, analyzer, TRANSMON, **IFS)

    ifs = [row[0] for row in result["iq_table"]]
    assert ifs[0] == 50.0 and ifs[-1] == 3000.0
    assert [r["if_mhz"] for r in result["suppression"]] == ifs
    assert all(r["image_below_wanted_db"] > 50 for r in result["suppression"])


def test_needs_an_iq_output_with_an_lo():
    board, analyzer = bench(TRANSMON, 0.0)
    with pytest.raises(ValueError, match="I/Q"):
        calibrate(board, analyzer, TRANSMON.model_copy(update={"output_path": "real"}), **IFS)
    with pytest.raises(ValueError, match="LO"):
        calibrate(board, analyzer, TRANSMON.model_copy(update={"lo_mhz": None}), **IFS)


def test_says_so_when_the_analyzer_sees_no_tone():
    board = FakeBoard(SOCCFG, lambda program: [])
    analyzer = FakeIqMixer(board, 6000.0)  # the analyzer looks around another LO

    with pytest.raises(ValueError, match="cable"):
        calibrate(board, analyzer, TRANSMON, **IFS)
    assert board.playing is None
