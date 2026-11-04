from pathlib import Path

import numpy as np
import pytest
from qick import QickConfig

from qick_interface.board import FakeBoard
from qick_interface.measurements.two_tone import TwoTone, TwoToneParams
from qick_interface.profiles import SetupProfile

SOCCFG = QickConfig(str(Path(__file__).parent / "fixtures" / "soccfg_rfsoc4x2.json"))
TRANSMON = SetupProfile(chip="Transmon A", lo_mhz=6800.0, output_path="iq",
                        i_dac="DAC_A", q_dac="DAC_B")


def window_start_us(program):
    """When the readout window opens in the program's timeline (its trigger time), in µs."""
    return next(m.t for m in program.macro_list if type(m).__name__ == "Trigger" and m.ros)


def qubit_at(qubit_if_mhz, width_mhz=1.0):
    """The readout signal drops when the qubit tone hits the qubit transition."""
    def simulate(program):
        f = TwoTone.qubit_if_axis(program)
        return [1 - 0.5 / (1 + ((f - qubit_if_mhz) / width_mhz) ** 2) + 0j]
    return simulate


def test_dip_appears_at_the_qubit_rf_frequency():
    params = TwoToneParams(qubit_start_mhz=9900.0, qubit_stop_mhz=10200.0, points=601,
                           readout_freq_mhz=7000.0, rounds=2)

    updates = list(TwoTone.run(FakeBoard(SOCCFG, qubit_at(3250.0)), TRANSMON, params))

    last = updates[-1]
    assert abs(last.x[np.argmin(last.traces["|S21| (dB)"])] - 10050.0) < 1.0
    assert [u.round for u in updates] == [1, 2]


FLUXONIUM = SetupProfile(chip="Fluxonium A", lo_mhz=6800.0, readout_dac="DAC_B",
                         control_dac="DAC_A")


def test_control_line_sends_the_qubit_tone_straight_from_its_own_dac():
    programs = []

    def capture(program):
        programs.append(program)
        return qubit_at(500.0, width_mhz=0.5)(program)

    params = TwoToneParams(qubit_start_mhz=400.0, qubit_stop_mhz=600.0, points=401,
                           readout_freq_mhz=7000.0, rounds=1)
    last = list(TwoTone.run(FakeBoard(SOCCFG, capture), FLUXONIUM, params))[-1]

    p = programs[0]
    assert p.pulses["qubit"].gen_chs == [1]    # DAC_A: the control line, no mixer
    assert p.pulses["readout"].gen_chs == [0]  # DAC_B: the readout line, through the LO
    assert abs(last.x[np.argmin(last.traces["|S21| (dB)"])] - 500.0) < 1.0  # RF = DAC frequency
    assert p.get_pulse_param("readout", "freq") == pytest.approx(200.0, abs=1e-3)


def test_the_window_opens_after_the_setups_time_of_flight():
    programs = []

    def capture(program):
        programs.append(program)
        return qubit_at(3250.0)(program)

    list(TwoTone.run(FakeBoard(SOCCFG, capture), TRANSMON.model_copy(update={"time_of_flight_us": 0.45}), TwoToneParams(qubit_start_mhz=9900.0, qubit_stop_mhz=10200.0, points=11, readout_freq_mhz=7000.0, rounds=1)))

    assert window_start_us(programs[0]) == pytest.approx(0.45, abs=0.002)
