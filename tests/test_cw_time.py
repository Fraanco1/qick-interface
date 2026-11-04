from pathlib import Path

import numpy as np
import pytest
from qick import QickConfig

from qick_interface.board import FakeBoard
from qick_interface.measurements.cw_time import CwTime, CwTimeParams
from qick_interface.profiles import SetupProfile

SOCCFG = QickConfig(str(Path(__file__).parent / "fixtures" / "soccfg_rfsoc4x2.json"))
PROFILE = SetupProfile(chip="Test chip", lo_mhz=6000.0, sideband="upper")


def sweeps_numbered():
    """Each sweep returns a constant |S21| equal to its sweep number: 1, 2, 3, …"""
    count = 0

    def simulate(program):
        nonlocal count
        count += 1
        return [np.full(program.cfg["points"], count, complex)]
    return simulate


def run_until(n_sweeps, simulate, **params):
    updates = []
    defaults = dict(freq_mhz=6150.0, points=101)
    sweeps = CwTime.run(FakeBoard(SOCCFG, simulate), PROFILE, CwTimeParams(**{**defaults, **params}),
                        should_stop=lambda: len(updates) >= n_sweeps)
    for u in sweeps:
        updates.append(u)
    return updates


def test_x_axis_is_the_time_of_each_point():
    u = run_until(1, sweeps_numbered(), points=101, readout_length_us=2.0, averages=3)[0]

    assert u.x_axis == {"title": "Time", "unit": "µs"}
    assert u.x[0] == 0
    assert np.diff(u.x) == pytest.approx(6.15, abs=0.01)  # 3 windows of 2 µs, each followed by a 50 ns gap


def test_windows_leave_the_readout_its_dead_time_and_the_axis_uses_the_spacing_the_board_plays():
    programs = []

    def capture(program):
        programs.append(program)
        return [np.ones(program.cfg["points"], complex)]

    u = run_until(1, capture, readout_length_us=1.2345, averages=1)[0]

    window = SOCCFG.cycles2us(SOCCFG.us2cycles(1.2345, ro_ch=0), ro_ch=0)  # as QICK rounds the readout
    tproc_cycle = 1 / SOCCFG["tprocs"][0]["f_time"]
    spacing = programs[0].cfg["spacing"]
    # back to back (gap < 30 ns) the readout drops triggers and stale buffer entries come back (bench, 2026-11-04)
    assert window + 0.05 <= spacing < window + 0.05 + tproc_cycle
    assert spacing / tproc_cycle == pytest.approx(round(spacing / tproc_cycle))  # a whole number of tProc cycles
    assert np.diff(u.x) == pytest.approx(spacing)


def test_long_sweeps_are_shown_in_ms():
    u = run_until(1, sweeps_numbered(), points=1001, readout_length_us=10.0)[0]

    assert u.x_axis["unit"] == "ms"
    assert u.x[-1] == pytest.approx(10.05, abs=0.01)  # 1000 spacings of 10 µs + 50 ns


def test_runs_until_stopped_showing_each_sweep_and_saving_all_of_them():
    updates = run_until(4, sweeps_numbered(), gain=1.0)

    assert [u.round for u in updates] == [1, 2, 3, 4]
    assert all(u.rounds is None for u in updates)  # continuous: no fixed number of sweeps
    last = updates[-1]
    assert last.traces["|S21| (dB)"] == pytest.approx(20 * np.log10(4))  # the 4th sweep, not an average
    s21 = np.asarray(last.raw["s21"])
    assert s21.shape == (4, 101)
    assert s21[:, 0] == pytest.approx([1, 2, 3, 4])
    assert len(last.raw["sweep_end_unix_s"]) == 4


def test_tone_stays_on_at_the_requested_frequency():
    programs = []

    def capture(program):
        programs.append(program)
        return [np.ones(program.cfg["points"], complex)]

    run_until(1, capture, freq_mhz=6150.0, gain=0.3)

    p = programs[0]
    assert p.pulses["probe"].params["mode"] == "periodic"
    assert p.get_pulse_param("probe", "freq") == pytest.approx(150.0, abs=1e-3)
    assert p.get_pulse_param("probe", "gain") == pytest.approx(0.3, abs=1e-4)
