from pathlib import Path

import numpy as np
import pytest
from qick import QickConfig

from qick_interface.board import FakeBoard
from qick_interface.measurements.resonator_sweep import ResonatorSweep, ResonatorSweepParams
from qick_interface.profiles import SetupProfile

SOCCFG = QickConfig(str(Path(__file__).parent / "fixtures" / "soccfg_rfsoc4x2.json"))
PROFILE = SetupProfile(chip="Test chip", lo_mhz=6000.0, sideband="upper")


def window_start_us(program):
    """When the readout window opens in the program's timeline (its trigger time), in µs."""
    return next(m.t for m in program.macro_list if type(m).__name__ == "Trigger" and m.ros)


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
    iq_profile = SetupProfile(chip="Transmon A", lo_mhz=6800.0,
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


def test_cw_mode_keeps_the_tone_on_and_still_finds_the_resonance():
    programs = []

    def capture(program):
        programs.append(program)
        return notch(if_center_mhz=150.0)(program)

    updates = run(FakeBoard(SOCCFG, capture), mode="cw", settle_us=20.0)

    last = updates[-1]
    assert abs(last.x[np.argmin(last.traces["|S21| (dB)"])] - 6150.0) < 0.5
    assert programs[0].pulses["probe"].params["mode"] == "periodic"


def chip_seen_by_the_board(profile, gain_scales=True):
    """A notch at RF 6150 MHz as the board receives it: scaled by the tone's gain, and on the
    lower sideband (RF = LO − IF) with its phase mirrored, as a real mixer delivers it."""
    def response(rf):
        return 1 - 0.9 / (1 + 2j * (rf - 6150.0) / 2.0)

    def simulate(program):
        f = ResonatorSweep.if_axis(program)
        lower = profile.sideband == "lower"
        seen = response(profile.lo_mhz - f if lower else profile.lo_mhz + f)
        seen = np.conj(seen) if lower else seen
        return [seen * (program.get_pulse_param("probe", "gain") if gain_scales else 1)]
    return response, simulate


def test_s21_does_not_change_with_the_gain():
    _, simulate = chip_seen_by_the_board(PROFILE)
    low, high = (run(FakeBoard(SOCCFG, simulate), gain=g, rounds=1)[-1].raw["s21"] for g in (0.25, 0.5))

    assert np.abs(low) == pytest.approx(np.abs(high), rel=1e-3)


def test_lower_sideband_shows_the_chip_phase_not_its_mirror_image():
    lower = SetupProfile(chip="Test chip", lo_mhz=6300.0, sideband="lower")
    response, simulate = chip_seen_by_the_board(lower)
    params = ResonatorSweepParams(rf_start_mhz=6100.0, rf_stop_mhz=6200.0, points=401, gain=1.0, rounds=1)

    u = list(ResonatorSweep.run(FakeBoard(SOCCFG, simulate), lower, params))[-1]

    assert u.raw["s21"] == pytest.approx(response(u.x), abs=1e-3)


def chip_behind_cable(program, profile=PROFILE, delay_us=0.216):
    """A notch at RF 6150 MHz behind 216 ns of electrical delay (like the board's own latency)."""
    f = ResonatorSweep.if_axis(program)
    return [chip_seen_by_the_board(profile, gain_scales=False)[0](profile.lo_mhz + f)
            * np.exp(-2j * np.pi * f * delay_us)]


def phase_error(u):
    """How far the phase trace is from the chip's own phase, apart from a constant offset (°)."""
    response, _ = chip_seen_by_the_board(PROFILE)
    diff = np.exp(1j * np.radians(u.traces["Phase (°)"])) / np.exp(1j * np.angle(response(u.x)))
    return np.degrees(np.ptp(np.unwrap(np.angle(diff))))


def test_every_sweep_reports_its_fitted_electrical_delay():
    u = run(FakeBoard(SOCCFG, chip_behind_cable), rf_start_mhz=6050.0, rf_stop_mhz=7050.0, points=2001, rounds=1)[-1]

    assert u.info["Electrical delay (ns)"] == pytest.approx(216.0, abs=0.5)


def test_a_stored_delay_keeps_the_resonance_phase_on_a_narrow_sweep():
    stored = PROFILE.model_copy(update={"electrical_delay_ns": 216.0})
    narrow = dict(rf_start_mhz=6145.0, rf_stop_mhz=6155.0, points=401, rounds=1)

    fitted = run(FakeBoard(SOCCFG, chip_behind_cable), **narrow)[-1]
    kept = list(ResonatorSweep.run(FakeBoard(SOCCFG, chip_behind_cable), stored,
                                   ResonatorSweepParams(**narrow)))[-1]

    assert phase_error(kept) < 0.1    # only a constant offset removed
    assert phase_error(fitted) > 5    # the per-sweep fit tilts the resonance's own phase


def test_the_window_opens_after_the_setups_time_of_flight():
    profile = PROFILE.model_copy(update={"time_of_flight_us": 0.45})
    program, _, _ = ResonatorSweep.program(FakeBoard(SOCCFG, notch(150.0)), profile,
                                           ResonatorSweepParams(rf_start_mhz=6100.0, rf_stop_mhz=6200.0))

    assert window_start_us(program) == pytest.approx(0.45, abs=0.002)
