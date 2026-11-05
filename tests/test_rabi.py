from pathlib import Path

import numpy as np
import pytest
from qick import QickConfig

from qick_interface.board import FakeBoard
from qick_interface.measurements.rabi import Rabi, RabiParams
from qick_interface.profiles import SetupProfile

SOCCFG = QickConfig(str(Path(__file__).parent / "fixtures" / "soccfg_rfsoc4x2.json"))
TRANSMON = SetupProfile(chip="Transmon A", lo_mhz=6800.0, output_path="iq",
                        i_dac="DAC_A", q_dac="DAC_B")
BASE = dict(qubit_freq_mhz=10050.0, readout_freq_mhz=7000.0, points=101, rounds=1)


def window_start_us(program):
    """When the readout window opens in the program's timeline (its trigger time), in µs."""
    return next(m.t for m in program.macro_list if type(m).__name__ == "Trigger" and m.ros)


def oscillating(x_pi, decay=None):
    """Readout signal of a qubit driven to the excited state at x_pi, in an arbitrary I/Q direction."""
    def simulate(program):
        x = Rabi.x_values(program)
        excited = 0.5 - 0.5 * np.cos(np.pi * x / x_pi) * (np.exp(-x / decay) if decay else 1)
        return [(200 + 60 * excited) * np.exp(0.7j) + 30]
    return simulate


def test_amplitude_rabi_finds_the_pi_pulse_gain():
    params = RabiParams(**BASE, sweep="amplitude", start=0.0, stop=1.0)

    last = list(Rabi.run(FakeBoard(SOCCFG, oscillating(0.4)), TRANSMON, params))[-1]

    assert last.info["π-pulse gain"] == pytest.approx(0.4, abs=0.005)
    assert {"Signal", "Fit", "Phase (°)", "Signal (mV)", "Fit (mV)"} <= set(last.traces)
    assert last.x_axis == {"title": "Qubit gain", "unit": ""}


def test_length_rabi_finds_the_pi_pulse_length_despite_decay():
    params = RabiParams(**BASE, sweep="length", start=0.01, stop=0.6, qubit_gain=0.5)

    last = list(Rabi.run(FakeBoard(SOCCFG, oscillating(0.12, decay=0.5)), TRANSMON, params))[-1]

    assert last.info["π-pulse length (µs)"] == pytest.approx(0.12, abs=0.003)
    assert last.x_axis == {"title": "Qubit pulse length", "unit": "µs"}


def test_no_pi_pulse_is_reported_when_there_is_no_oscillation():
    rng = np.random.default_rng(1)

    def noise(program):
        n = Rabi.x_values(program).size
        return [200 + rng.normal(0, 1, n) + 1j * rng.normal(0, 1, n)]

    params = RabiParams(**BASE, sweep="amplitude", start=0.0, stop=1.0)
    last = list(Rabi.run(FakeBoard(SOCCFG, noise), TRANSMON, params))[-1]

    assert last.info == {}


def test_rabi_drives_the_qubit_on_the_control_line_when_the_setup_has_one():
    fluxonium = SetupProfile(chip="Fluxonium A", lo_mhz=6800.0, readout_dac="DAC_B",
                             control_dac="DAC_A")
    programs = []

    def capture(program):
        programs.append(program)
        return oscillating(0.4)(program)

    params = RabiParams(qubit_freq_mhz=500.0, readout_freq_mhz=7000.0, rounds=1)
    list(Rabi.run(FakeBoard(SOCCFG, capture), fluxonium, params))

    assert programs[0].pulses["qubit"].gen_chs == [1]
    assert programs[0].get_pulse_param("qubit", "freq") == pytest.approx(500.0, abs=1e-3)


def test_the_window_opens_after_the_setups_time_of_flight():
    programs = []

    def capture(program):
        programs.append(program)
        return oscillating(0.4)(program)

    list(Rabi.run(FakeBoard(SOCCFG, capture), TRANSMON.model_copy(update={"time_of_flight_us": 0.45}), RabiParams(**BASE, sweep="amplitude", start=0.0, stop=1.0)))

    assert window_start_us(programs[0]) == pytest.approx(0.45, abs=0.002)


def plays_for_hours(program):
    """The program repeats its shot for far longer than anyone watches a scope (at least 1e12 shots)."""
    return np.prod([float(n) for n in program.loop_dims]) >= 1e12


def marker_at_shot_start(program):
    """PMOD0_0 goes high once per shot, when the qubit pulse starts."""
    markers = [m for m in program.macro_list if type(m).__name__ == "Trigger" and m.pins]
    return len(markers) == 1 and markers[0].t == 0


@pytest.mark.parametrize("sweep, at, param, expected", [
    ("amplitude", {"scope_gain": 0.37}, "gain", 0.37),
    ("length", {"scope_length_us": 0.25}, "length", 0.25),
])
def test_the_scope_sequence_repeats_one_rabi_shot_at_the_value_typed(sweep, at, param, expected):
    params = RabiParams(**BASE, sweep=sweep, start=0.0, stop=1.0, **at)

    program = Rabi.sequence(SOCCFG, TRANSMON, params)

    assert program.get_pulse_param("qubit", param) == pytest.approx(expected, abs=0.005)
    assert program.get_pulse_param("readout", "gain") == pytest.approx(params.readout_gain, abs=0.001)
    assert plays_for_hours(program)
    assert marker_at_shot_start(program)


SHORTEST = "The shortest qubit pulse is 4.9 ns"  # 3 cycles of the generators' 614.4 MHz clock


@pytest.mark.parametrize("params", [
    dict(sweep="length", start=0.0, stop=0.6),     # the Start a length sweep begins with
    dict(sweep="length", start=0.004, stop=0.6),
    dict(sweep="amplitude", sigma_us=0.001),         # 4σ = 4 ns
])
def test_a_qubit_pulse_shorter_than_the_board_allows_is_refused_in_plain_words(params):
    with pytest.raises(ValueError, match=SHORTEST):
        list(Rabi.run(FakeBoard(SOCCFG, oscillating(0.4)), TRANSMON, RabiParams(**{**BASE, **params})))


def test_the_scope_sequence_refuses_a_too_short_pulse_too():
    with pytest.raises(ValueError, match=SHORTEST):
        Rabi.sequence(SOCCFG, TRANSMON, RabiParams(**BASE, sweep="length", scope_length_us=0.002))


def test_the_shortest_pulses_the_board_allows_are_accepted():
    Rabi.sequence(SOCCFG, TRANSMON, RabiParams(**BASE, sweep="length", scope_length_us=0.005))
    Rabi.sequence(SOCCFG, TRANSMON, RabiParams(**BASE, sweep="amplitude", sigma_us=0.0013))


def gap_before_readout_us(program):
    """The wait between the end of the qubit pulse and the start of the readout pulse."""
    macros = program.macro_list
    readout = next(i for i, m in enumerate(macros) if type(m).__name__ == "Pulse" and m.name == "readout")
    return next(m.t for m in reversed(macros[:readout]) if type(m).__name__ == "Delay" and m.auto)


@pytest.mark.parametrize("gap", [None, 0.0, 0.2])
def test_the_readout_starts_after_the_delay_set_after_the_qubit_pulse(gap):
    params = RabiParams(**BASE, **({} if gap is None else {"readout_gap_us": gap}))

    assert gap_before_readout_us(Rabi.sequence(SOCCFG, TRANSMON, params)) == (0.05 if gap is None else gap)


EDGES = dict(sweep="length", shape="gaussian edges", edge_sigma_us=0.005)


def oscillating_with_edges(x_pi_total, sigma_us):
    """A length sweep of a flat_top pulse: its ramps (8σ in all) rotate the qubit as much as 2.51σ of flat
    part, so the qubit is excited when the flat part reaches x_pi_total − 2.51σ."""
    def simulate(program):
        x = Rabi.x_values(program) + 2.51 * sigma_us
        excited = 0.5 - 0.5 * np.cos(np.pi * x / x_pi_total)
        return [(200 + 60 * excited) * np.exp(0.7j) + 30]
    return simulate


def test_a_length_sweep_with_gaussian_edges_sweeps_the_flat_part_between_8_sigma_of_ramps():
    programs = []

    def capture(program):
        programs.append(program)
        return oscillating_with_edges(0.12, 0.005)(program)

    params = RabiParams(**BASE, **EDGES, start=0.01, stop=0.6, qubit_gain=0.5)
    last = list(Rabi.run(FakeBoard(SOCCFG, capture), TRANSMON, params))[-1]

    flat = programs[0].get_pulse_param("qubit", "length", as_array=True)
    total = programs[0].get_pulse_param("qubit", "total_length", as_array=True)
    assert flat[0] == pytest.approx(0.01, abs=0.002)
    assert total - flat == pytest.approx(np.full(flat.size, 8 * 0.005), abs=0.002)
    assert last.info["π-pulse flat length (µs)"] == pytest.approx(0.12 - 2.51 * 0.005, abs=0.003)
    assert last.x_axis == {"title": "Flat length (plus 0.04 µs of edges)", "unit": "µs"}


def test_flat_is_the_default_shape():
    program = Rabi.sequence(SOCCFG, TRANSMON, RabiParams(**BASE, sweep="length", scope_length_us=0.1))

    assert program.get_pulse_param("qubit", "total_length") == pytest.approx(0.1, abs=0.002)


def test_edges_too_short_for_the_board_are_refused_in_plain_words():
    params = RabiParams(**BASE, **{**EDGES, "edge_sigma_us": 0.001}, start=0.01, stop=0.6)  # 4σ ramp = 4 ns

    with pytest.raises(ValueError, match=SHORTEST):
        list(Rabi.run(FakeBoard(SOCCFG, oscillating(0.4)), TRANSMON, params))


def test_the_scope_marker_covers_the_edges_too():
    program = Rabi.sequence(SOCCFG, TRANSMON, RabiParams(**BASE, **EDGES, scope_length_us=0.1))

    marker = next(m for m in program.macro_list if type(m).__name__ == "Trigger" and m.pins)
    assert marker.width == pytest.approx(0.1 + 8 * 0.005, abs=0.002)


LONGEST = "The longest qubit envelope is 6.67 µs"  # the generator's waveform memory: 65536 samples at 9830.4 MHz


def test_a_gaussian_longer_than_the_waveform_memory_is_refused_in_plain_words():
    # (Edge σ is capped by its field at 0.5 µs: 8σ = 4 µs fits)
    params = RabiParams(**BASE, sweep="amplitude", start=0.0, stop=1.0, sigma_us=1.7)  # 4σ = 6.8 µs

    with pytest.raises(ValueError, match=LONGEST):
        Rabi.sequence(SOCCFG, TRANSMON, params)
    with pytest.raises(ValueError, match=LONGEST):
        list(Rabi.run(FakeBoard(SOCCFG, oscillating(0.4)), TRANSMON, params))


def test_the_longest_envelope_that_fits_is_accepted():
    Rabi.sequence(SOCCFG, TRANSMON, RabiParams(**BASE, sweep="amplitude", sigma_us=1.66))


def oscillating_along(angle_deg, seed, x_pi=0.4):
    """A qubit driven to |1⟩ at x_pi, its readout moving along a line at angle_deg in the I/Q plane, with noise."""
    rng = np.random.default_rng(seed)

    def simulate(program):
        x = Rabi.x_values(program)
        excited = 0.5 - 0.5 * np.cos(np.pi * x / x_pi)
        noise = rng.normal(0, 1, x.size) + 1j * rng.normal(0, 1, x.size)
        return [200 + 30j + 60 * excited * np.exp(1j * np.radians(angle_deg)) + noise]
    return simulate


@pytest.mark.parametrize("angle", [0, 45, 135, 225, 300])
def test_the_signal_rises_from_the_zero_drive_end_whatever_the_iq_direction(angle):
    # without a rule, the eigensolver picks the sign, at random near a diagonal: Tr1 flipped between rounds
    for seed in range(20):
        params = RabiParams(**BASE, sweep="amplitude", start=0.0, stop=1.0)
        last = list(Rabi.run(FakeBoard(SOCCFG, oscillating_along(angle, seed)), TRANSMON, params))[-1]

        signal = last.traces["Signal"]
        assert signal[0] < 0 < signal[np.argmin(np.abs(last.x - 0.4))], (angle, seed)  # |0⟩ low, π high


def test_the_raw_i_q_and_magnitude_are_traces_too():
    params = RabiParams(**BASE, sweep="amplitude", start=0.0, stop=1.0)
    last = list(Rabi.run(FakeBoard(SOCCFG, oscillating_along(30, 0)), TRANSMON, params))[-1]

    s21 = last.raw["s21"]
    assert last.traces["I"] == pytest.approx(s21.real)
    assert last.traces["Q"] == pytest.approx(s21.imag)
    assert last.traces["|S21|"] == pytest.approx(np.abs(s21))
    for name in ("I", "Q", "|S21|"):
        assert f"{name} (mV)" in last.traces


def test_the_fit_is_drawn_in_the_iq_plane_along_the_direction_the_points_move():
    params = RabiParams(**BASE, sweep="amplitude", start=0.0, stop=1.0)
    last = list(Rabi.run(FakeBoard(SOCCFG, oscillating_along(30, 0)), TRANSMON, params))[-1]

    fit = last.traces["Fit I"] + 1j * last.traces["Fit Q"]
    direction = np.angle(fit[np.argmax(last.traces["Fit"])] - fit[np.argmin(last.traces["Fit"])], deg=True)
    assert direction == pytest.approx(30, abs=2)  # from |0⟩ toward |1⟩
    noise_rms = np.sqrt(2) / params.readout_gain  # S21 is divided by the readout gain
    assert np.sqrt(np.mean(np.abs(fit - last.raw["s21"]) ** 2)) < 1.2 * noise_rms  # through the points
    assert "Fit I (mV)" in last.traces and "Fit Q (mV)" in last.traces
