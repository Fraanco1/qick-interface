from pathlib import Path

import numpy as np
from qick import QickConfig

from qick_interface.board import FakeBoard
from qick_interface.measurements.two_tone import TwoTone, TwoToneParams
from qick_interface.profiles import SetupProfile

SOCCFG = QickConfig(str(Path(__file__).parent / "fixtures" / "soccfg_rfsoc4x2.json"))
TRANSMON = SetupProfile(chip="Transmon A", chip_type="transmon", lo_mhz=6800.0, output_path="iq",
                        i_dac="DAC_A", q_dac="DAC_B")


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
