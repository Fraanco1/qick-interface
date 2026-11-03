from pathlib import Path

import numpy as np
import pytest
from qick import QickConfig

from qick_interface.board import FakeBoard
from qick_interface.measurements.resonator_sweep import ResonatorSweep, ResonatorSweepParams
from qick_interface.profiles import SetupProfile

SOCCFG = QickConfig(str(Path(__file__).parent / "fixtures" / "soccfg_rfsoc4x2.json"))
PROFILE = SetupProfile(chip="Test chip", chip_type="transmon", lo_mhz=6000.0, sideband="upper")


def notch(if_center_mhz, width_mhz=2.0, delay_us=0.05):
    """Simulated hanger resonator behind a cable with the given electrical delay."""
    def simulate(program):
        f = ResonatorSweep.if_axis(program)
        s21 = 1 - 0.9 / (1 + 2j * (f - if_center_mhz) / width_mhz)
        return [s21 * np.exp(-2j * np.pi * f * delay_us)]
    return simulate


def run(board, **params):
    defaults = dict(rf_start_mhz=6100.0, rf_stop_mhz=6200.0, points=401, rounds=3)
    return list(ResonatorSweep.run(board, PROFILE, ResonatorSweepParams(**{**defaults, **params})))


def test_dip_appears_at_the_resonator_rf_frequency():
    updates = run(FakeBoard(SOCCFG, notch(if_center_mhz=150.0)))

    last = updates[-1]
    rf_at_min = last.x[np.argmin(last.traces["|S21| (dB)"])]
    assert abs(rf_at_min - 6150.0) < 0.5
    assert [u.round for u in updates] == [1, 2, 3]


def test_phase_has_the_electrical_delay_removed():
    def cable_only(program):
        f = ResonatorSweep.if_axis(program)
        return [np.exp(-2j * np.pi * f * 0.05)]  # 50 ns of cable

    phase = run(FakeBoard(SOCCFG, cable_only))[-1].traces["Phase (°)"]

    assert np.ptp(phase) < 0.1
    assert abs(np.mean(phase)) < 0.1  # centred on 0°, like a PNA after electrical delay


def test_run_stops_after_the_current_round_when_asked():
    updates = []
    params = ResonatorSweepParams(rf_start_mhz=6100.0, rf_stop_mhz=6200.0, rounds=10)
    sweep = ResonatorSweep.run(FakeBoard(SOCCFG, notch(150.0)), PROFILE, params,
                               should_stop=lambda: len(updates) >= 2)
    for update in sweep:
        updates.append(update)

    assert len(updates) == 2


def test_iq_output_plays_i_and_q_on_two_dacs_with_the_calibrated_offset():
    iq_profile = SetupProfile(chip="Transmon A", chip_type="transmon", lo_mhz=6800.0,
                              output_path="iq", i_dac="DAC_A", q_dac="DAC_B",
                              iq_phase_deg=93.0, iq_gain_ratio=0.9)
    programs = []

    def capture(program):
        programs.append(program)
        return [np.ones(ResonatorSweep.if_axis(program).size, complex)]

    params = ResonatorSweepParams(rf_start_mhz=6900.0, rf_stop_mhz=7100.0, points=101, gain=0.5, rounds=1)
    list(ResonatorSweep.run(FakeBoard(SOCCFG, capture), iq_profile, params))

    p = programs[0]
    assert p.pulses["probe"].gen_chs == [1]    # DAC_A
    assert p.pulses["probe_q"].gen_chs == [0]  # DAC_B
    assert p.get_pulse_param("probe", "gain") == pytest.approx(0.5, abs=1e-4)
    assert p.get_pulse_param("probe_q", "gain") == pytest.approx(0.45, abs=1e-4)
    assert p.get_pulse_param("probe_q", "phase") - p.get_pulse_param("probe", "phase") == pytest.approx(93.0, abs=0.01)
