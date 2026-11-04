from pathlib import Path

import numpy as np
import pytest
from qick import QickConfig

from qick_interface.board import FakeBoard
from qick_interface.fake_scope import FakeScope
from qick_interface.iq_delay import measure
from qick_interface.profiles import SetupProfile
from qick_interface.tone import OutputTone, tone_program

SOCCFG = QickConfig(str(Path(__file__).parent / "fixtures" / "soccfg_rfsoc4x2.json"))
IQ = SetupProfile(chip="IQ", lo_mhz=6000.0, output_path="iq", i_dac="DAC_A", q_dac="DAC_B")


def bench(q_lead_ps, i_channel="CH3", q_channel="CH1", q_cabled=True):
    board = FakeBoard(SOCCFG, None)
    wiring = {"DAC_A": (i_channel, 0.0)}
    if q_cabled:
        wiring["DAC_B"] = (q_channel, q_lead_ps)
    return board, FakeScope(board, wiring)


@pytest.mark.parametrize("q_lead_ps", [3300.0, 1550.0, -800.0])
def test_finds_how_far_the_q_dac_runs_ahead_and_on_which_channels(q_lead_ps):
    board, scope = bench(q_lead_ps)

    result = measure(board, scope, IQ)

    assert result["iq_delay_ps"] == pytest.approx(q_lead_ps, abs=20)
    assert (result["i_channel"], result["q_channel"]) == ("CH3", "CH1")
    assert board.playing is None  # leaves the outputs silent


def test_with_the_measured_delay_stored_i_and_q_leave_90_degrees_apart_at_every_frequency():
    board, scope = bench(3300.0)
    profile = IQ.model_copy(update={"lo_mhz": None, "iq_delay_ps": measure(board, scope, IQ)["iq_delay_ps"]})

    for f in (20.0, 75.0, 150.0):
        board.play(tone_program(SOCCFG, profile, OutputTone(chip="IQ", rf_mhz=f, gain=0.3)))
        (t, i), (_, q) = scope.waveform("CH3"), scope.waveform("CH1")
        w = 2 * np.pi * f * 1e6 * t
        phase = lambda v: np.angle(np.sum(v * np.exp(-1j * w)), deg=True)
        assert (phase(q) - phase(i) + 180) % 360 - 180 == pytest.approx(90.0, abs=1.0)


def test_says_which_dac_is_missing_from_the_scope():
    board, scope = bench(3300.0, q_cabled=False)

    with pytest.raises(ValueError, match="DAC_B does not show on any scope channel"):
        measure(board, scope, IQ)


def test_needs_the_iq_output_path():
    board, scope = bench(0.0)

    with pytest.raises(ValueError, match="Output path to I/Q"):
        measure(board, scope, IQ.model_copy(update={"output_path": "real"}))


def test_puts_the_scope_settings_back():
    board, scope = bench(3300.0)
    scope.write("CH2:SCALE 1.0")
    scope.write("TRIGGER:A:MODE NORMAL")

    measure(board, scope, IQ)

    assert scope.query("CH2:SCALE?") == "1.0"
    assert scope.query("TRIGGER:A:MODE?") == "NORMAL"
