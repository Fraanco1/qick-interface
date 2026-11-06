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


# ---- the Q delay in the pulse envelopes, not only in the carrier's phase ----
from qick_interface.board import gen_channel  # noqa: E402
from qick_interface.measurements.rabi import Rabi, RabiParams  # noqa: E402

I_GEN, Q_GEN = gen_channel(SOCCFG, "DAC_A"), gen_channel(SOCCFG, "DAC_B")
SAMPLE_PS = 1e6 / (SOCCFG["gens"][I_GEN]["f_fabric"] * SOCCFG["gens"][I_GEN]["samps_per_clk"])  # 101.7 ps
CYCLE_PS = 1e6 / SOCCFG["gens"][I_GEN]["f_fabric"]                                               # 1627.6 ps
RABI = dict(qubit_freq_mhz=100.0, readout_freq_mhz=200.0)


def start_ps(program, name):
    """When the pulse is scheduled to start, in ps."""
    return next(m.t for m in program.macro_list if type(m).__name__ == "Pulse" and m.name == name) * 1e6


def envelope(program, gen, name):
    return program.envelopes[gen]["envs"][name]["data"][:, 0].astype(float)


def half_height_crossings(env):
    """Where the envelope rises through and falls back through half its peak, in samples (interpolated)."""
    above = np.flatnonzero(env >= env.max() / 2)
    i, j = above[0], above[-1]
    rise = i - 1 + (env.max() / 2 - env[i - 1]) / (env[i] - env[i - 1])
    fall = j + (env[j] - env.max() / 2) / (env[j] - env[j + 1])
    return rise, fall


def lag_ps(program, pulse, env_name, lagging_gen, leading_gen, lagging_suffix, leading_suffix):
    """How much later the lagging DAC plays the envelope's half-height edges than the leading one, in ps."""
    start = start_ps(program, pulse + lagging_suffix) - start_ps(program, pulse + leading_suffix)
    lagging = half_height_crossings(envelope(program, lagging_gen, env_name))
    leading = half_height_crossings(envelope(program, leading_gen, env_name))
    return [start + (a - b) * SAMPLE_PS for a, b in zip(lagging, leading)]


@pytest.mark.parametrize("delay_ps", [3070.0, 500.0, 1627.6])
def test_q_plays_the_gaussian_later_by_the_q_delay_so_both_envelopes_leave_the_dacs_together(delay_ps):
    # Q's DAC runs delay_ps ahead: a whole number of cycles goes on Q's start, the rest into Q's envelope
    profile = IQ.model_copy(update={"iq_delay_ps": delay_ps})
    program = Rabi.sequence(SOCCFG, profile, RabiParams(**RABI, sigma_us=0.02))

    rise, fall = lag_ps(program, "qubit", "gauss", Q_GEN, I_GEN, "_q", "")
    assert rise == pytest.approx(delay_ps, abs=2) and fall == pytest.approx(delay_ps, abs=2)
    assert (start_ps(program, "qubit_q") - start_ps(program, "qubit")) % CYCLE_PS == pytest.approx(0, abs=0.5)


def test_with_q_running_behind_i_plays_later_instead():
    profile = IQ.model_copy(update={"iq_delay_ps": -3070.0})
    program = Rabi.sequence(SOCCFG, profile, RabiParams(**RABI, sigma_us=0.02))

    rise, fall = lag_ps(program, "qubit", "gauss", I_GEN, Q_GEN, "", "_q")
    assert rise == pytest.approx(3070, abs=2) and fall == pytest.approx(3070, abs=2)


def test_gaussian_edges_are_delayed_on_both_sides_of_the_flat_part():
    profile = IQ.model_copy(update={"iq_delay_ps": 3070.0})
    program = Rabi.sequence(SOCCFG, profile, RabiParams(**RABI, sweep="length", shape="gaussian edges",
                                                       edge_sigma_us=0.005, scope_length_us=0.1))

    # the envelope holds the rising half then the falling half; each half's edge moves by the same amount
    rise, fall = lag_ps(program, "qubit", "edges", Q_GEN, I_GEN, "_q", "")
    assert rise == pytest.approx(3070, abs=5) and fall == pytest.approx(3070, abs=5)
    q = envelope(program, Q_GEN, "edges")
    assert q[len(q) // 2] == pytest.approx(q.max())  # the falling half starts at the top, where the flat part ends


def test_flat_pulses_move_by_the_nearest_whole_cycle():
    profile = IQ.model_copy(update={"iq_delay_ps": 3070.0})
    program = Rabi.sequence(SOCCFG, profile, RabiParams(**RABI, sweep="length", scope_length_us=0.1))

    assert start_ps(program, "qubit_q") - start_ps(program, "qubit") == pytest.approx(2 * CYCLE_PS, abs=0.5)


def test_without_a_q_delay_i_and_q_play_the_same_envelope_at_the_same_time():
    program = Rabi.sequence(SOCCFG, IQ, RabiParams(**RABI, sigma_us=0.02))

    assert start_ps(program, "qubit_q") == start_ps(program, "qubit")
    assert envelope(program, Q_GEN, "gauss") == pytest.approx(envelope(program, I_GEN, "gauss"))


# ---- the Q phase and gain from a table against IF (TX I/Q calibration) ----
TABLE = IQ.model_copy(update={"iq_table": [(100.0, 80.0, 0.9), (300.0, 100.0, 1.1)], "iq_phase_deg": 45.0})


def q_over_i_gain(program, name, as_array=False):
    return (np.asarray(program.get_pulse_param(name + "_q", "gain", as_array=as_array))
            / np.asarray(program.get_pulse_param(name, "gain", as_array=as_array)))


@pytest.mark.parametrize("if_mhz, phase, ratio", [(150.0, 85.0, 0.95), (200.0, 90.0, 1.0), (50.0, 80.0, 0.9),
                                                  (400.0, 100.0, 1.1)])
def test_a_tone_takes_the_q_phase_and_gain_of_the_table_at_its_if(if_mhz, phase, ratio):
    # interpolated between the table's points and held beyond its ends; the single Q phase (45°) is unused
    program = tone_program(SOCCFG, TABLE, OutputTone(chip="IQ", rf_mhz=if_mhz, gain=0.5))

    assert q_minus_i_deg(program, "tone") == pytest.approx(phase, abs=0.01)
    assert q_over_i_gain(program, "tone") == pytest.approx(ratio, abs=0.001)


def test_a_sweep_follows_the_table_in_a_straight_line_between_its_ends():
    params = ResonatorSweepParams(rf_start_mhz=120.0, rf_stop_mhz=280.0, points=9)

    program, if_mhz, _ = ResonatorSweep.program(FakeBoard(SOCCFG, None), TABLE, params)

    expected_phase = 80.0 + (np.asarray(if_mhz) - 100.0) * 0.1
    assert q_minus_i_deg(program, "probe", as_array=True) == pytest.approx(expected_phase, abs=0.05)
    assert q_over_i_gain(program, "probe", as_array=True) == pytest.approx(0.9 + (np.asarray(if_mhz) - 100.0) * 0.001, abs=0.002)
    i_gain = np.asarray(program.get_pulse_param("probe", "gain", as_array=True))
    assert np.ptp(i_gain) < 1e-4  # I keeps its gain along the sweep


def test_the_tuning_keys_do_not_override_a_table():
    program = tone_program(SOCCFG, TABLE, OutputTone(chip="IQ", rf_mhz=200.0, gain=0.5, iq_phase_deg=30.0))

    assert q_minus_i_deg(program, "tone") == pytest.approx(90.0, abs=0.01)
