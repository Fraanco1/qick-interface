from pathlib import Path

import numpy as np
import pytest
from qick import QickConfig

from qick_interface.board import FakeBoard
from qick_interface.profiles import SetupProfile
from qick_interface.time_of_flight import measure, program

SOCCFG = QickConfig(str(Path(__file__).parent / "fixtures" / "soccfg_rfsoc4x2.json"))
LOOPBACK = SetupProfile(chip="Loopback", lo_mhz=None, readout_dac="DAC_B", readout_adc="ADC_D")


def pulse_arriving_at(t_us, noise=4.0):
    """A board whose window records the test pulse arriving t_us after it was sent."""
    def simulate(prog):
        f_s = SOCCFG["readouts"][prog.cfg["inputs"][0]]["f_output"]
        t = np.arange(int(prog.cfg["window_us"] * f_s)) / f_s
        envelope = 1000 * ((t >= t_us) & (t < t_us + prog.cfg["pulse_us"]))
        noisy = envelope * np.exp(0.7j) + np.random.default_rng(0).normal(0, noise, (t.size, 2)) @ [1, 1j]
        return [noisy for _ in prog.cfg["inputs"]]
    return FakeBoard(SOCCFG, simulate)


@pytest.mark.parametrize("arrival", [0.29, 1.5])
def test_finds_when_the_pulse_reaches_the_adc(arrival):
    assert measure(pulse_arriving_at(arrival), LOOPBACK, None) == pytest.approx(arrival, abs=0.005)


def test_says_so_when_nothing_comes_back():
    with pytest.raises(ValueError, match="No pulse came back"):
        measure(pulse_arriving_at(99.0), LOOPBACK, None)


@pytest.mark.parametrize("profile, readout_freq, test_rf", [
    (LOOPBACK.model_copy(update={"lo_mhz": 6000.0}), 7000.0, 7020.0),  # off the resonator
    (LOOPBACK, None, 500.0),                                       # no readout frequency, no LO
    (LOOPBACK.model_copy(update={"lo_mhz": 6000.0}), None, 6100.0),
    (LOOPBACK.model_copy(update={"lo_mhz": 6000.0, "sideband": "lower"}), None, 5900.0),
])
def test_the_test_pulse_stays_off_the_resonator(profile, readout_freq, test_rf):
    prog = program(SOCCFG, profile, readout_freq)

    assert prog.cfg["rf_mhz"] == test_rf
