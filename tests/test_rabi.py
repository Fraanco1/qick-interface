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
    assert set(last.traces) == {"Signal", "Fit", "Phase (°)"}
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
