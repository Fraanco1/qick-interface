import time
from pathlib import Path

import numpy as np
import pytest
from qick import QickConfig

from qick_interface.board import FakeBoard, readout_channel
from qick_interface.measurements.oscilloscope import Oscilloscope, OscilloscopeParams
from qick_interface.power import FULL_SCALE_COUNTS, BoardCalibration
from qick_interface.profiles import SetupProfile

SOCCFG = QickConfig(str(Path(__file__).parent / "fixtures" / "soccfg_rfsoc4x2.json"))
LOOPBACK = SetupProfile(chip="Loopback", lo_mhz=None, readout_dac="DAC_B", readout_adc="ADC_C")
BASE = dict(readout_freq_mhz=500.0)
FS_MHZ = SOCCFG["readouts"][0]["fs"]       # 4423.68: the ADC's raw sample rate
RECORD = SOCCFG["mr_buf"]["maxlen"]        # 8192 samples, 1.85 µs


def sine_arriving(after_us=0.16, amplitude=7300.0):
    """A board whose raw record shows the readout pulse's carrier from after_us, on whichever ADC it records."""
    def simulate(program):
        t = program.cfg["record_start"] + np.arange(RECORD) / FS_MHZ
        on = (t >= after_us) & (t < after_us + program.cfg["readout_pulse"])
        return [amplitude * np.cos(2 * np.pi * program.cfg["readout_rf"] * t) * on]
    return simulate


def updates(board, profile, params, n=2):
    count = iter(range(10 ** 6))
    return list(Oscilloscope.run(board, profile, params, should_stop=lambda: next(count) >= n))


class RecordingBoard(FakeBoard):
    """Remembers which readout each record came from."""
    def __init__(self, *a, **kw):
        super().__init__(*a, **kw)
        self.recorded = []

    def capture_raw(self, program, ro):
        self.recorded.append(ro)
        return super().capture_raw(program, ro)


def test_it_shows_the_adcs_voltage_against_time_like_a_scope():
    params = OscilloscopeParams(**BASE, readout_pulse_us=1.0)
    last = updates(FakeBoard(SOCCFG, sine_arriving()), LOOPBACK, params)[-1]

    assert last.rounds is None  # redraws until Stop
    assert last.x.size == RECORD and last.x[1] - last.x[0] == pytest.approx(1 / FS_MHZ)  # µs, every raw sample
    ch1 = last.traces["Channel 1"]
    on = (last.x > 0.2) & (last.x < 1.1)
    assert ch1[on].max() == pytest.approx(7300, rel=0.01) and ch1[on].min() == pytest.approx(-7300, rel=0.01)
    assert np.all(ch1[last.x < 0.15] == 0)  # the carrier itself, from when it arrives
    assert np.all(np.isnan(last.traces["Channel 2"]))  # off by default: an empty window


def test_millivolts_follow_the_adc_calibration():
    last = updates(FakeBoard(SOCCFG, sine_arriving()), LOOPBACK, OscilloscopeParams(**BASE, readout_pulse_us=1.0))[-1]

    # a full-scale tone reads 32768 raw counts, and FULL_SCALE_COUNTS after the readout's downconversion
    mv_per_count = BoardCalibration().adc_linear_per_count("ADC_C", 500.0) * FULL_SCALE_COUNTS / 32768
    assert last.traces["Channel 1 (mV)"] == pytest.approx(last.traces["Channel 1"] * mv_per_count)


def test_channel_1_starts_on_the_setups_readout_input_and_channel_2_records_another_adc():
    board = RecordingBoard(SOCCFG, sine_arriving())
    updates(board, LOOPBACK, OscilloscopeParams(**BASE, channel_2="ADC_D"), n=1)

    assert board.recorded == [readout_channel(SOCCFG, "ADC_C"), readout_channel(SOCCFG, "ADC_D")]


def test_on_an_iq_return_path_channel_1_starts_on_the_i_input():
    board = RecordingBoard(SOCCFG, sine_arriving())
    iq = LOOPBACK.model_copy(update={"return_path": "iq", "i_adc": "ADC_D", "q_adc": "ADC_C"})
    updates(board, iq, OscilloscopeParams(**BASE), n=1)

    assert board.recorded == [readout_channel(SOCCFG, "ADC_D")]


def trigger(program):
    return next(m for m in program.macro_list if type(m).__name__ == "Trigger")


def test_the_record_passes_the_adc_input_through_and_starts_where_asked():
    program = Oscilloscope.program(SOCCFG, LOOPBACK, OscilloscopeParams(**BASE, record_start_us=0.5), "ADC_C")

    assert program.cfg["readout_config"]["outsel"] == "input"  # not downconverted
    assert trigger(program).mr and trigger(program).t == pytest.approx(0.5)
    assert trigger(program).pins == [0]  # PMOD0_0 marks the record for an external scope


def test_the_readout_pulse_is_played_as_set():
    params = OscilloscopeParams(readout_freq_mhz=480.0, readout_gain=0.3, readout_pulse_us=0.7)
    program = Oscilloscope.program(SOCCFG, LOOPBACK, params, "ADC_C")

    assert program.get_pulse_param("readout", "freq") == pytest.approx(480.0, abs=1e-3)
    assert program.get_pulse_param("readout", "gain") == pytest.approx(0.3, abs=1e-3)
    assert program.get_pulse_param("readout", "length") == pytest.approx(0.7, abs=0.002)


def readout_start_after_qubit_us(program):
    macros = program.macro_list
    readout = next(i for i, m in enumerate(macros) if type(m).__name__ == "Pulse" and m.name == "readout")
    return next(m.t for m in reversed(macros[:readout]) if type(m).__name__ == "Delay" and m.auto)


@pytest.mark.parametrize("shape, style, length_param, expected", [
    ("flat", "const", "length", 0.2),                 # a Two-tone shot
    ("gaussian", "arb", "total_length", 4 * 0.02),    # a Rabi amplitude shot
    ("gaussian edges", "flat_top", "total_length", 0.2 + 8 * 0.005),
])
def test_a_qubit_pulse_can_play_before_the_readout(shape, style, length_param, expected):
    params = OscilloscopeParams(**BASE, qubit_pulse=shape, qubit_freq_mhz=100.0, qubit_gain=0.4, qubit_length_us=0.2,
                                sigma_us=0.02, edge_sigma_us=0.005, readout_gap_us=0.1)
    program = Oscilloscope.program(SOCCFG, LOOPBACK, params, "ADC_C")

    assert program.pulses["qubit"].params["style"] == style
    assert program.get_pulse_param("qubit", length_param) == pytest.approx(expected, abs=0.004)
    assert program.get_pulse_param("qubit", "freq") == pytest.approx(100.0, abs=1e-3)
    assert readout_start_after_qubit_us(program) == pytest.approx(0.1)


def test_without_a_qubit_pulse_only_the_readout_plays():
    assert "qubit" not in Oscilloscope.program(SOCCFG, LOOPBACK, OscilloscopeParams(**BASE), "ADC_C").pulses


def test_a_qubit_pulse_needs_its_frequency():
    with pytest.raises(ValueError, match="Qubit frequency"):
        Oscilloscope.program(SOCCFG, LOOPBACK, OscilloscopeParams(**BASE, qubit_pulse="flat"), "ADC_C")


def test_it_redraws_at_most_five_times_a_second_however_fast_the_board_records():
    # each update carries whole traces to every browser; unthrottled, a fast record floods the server
    t0 = time.monotonic()
    ups = updates(FakeBoard(SOCCFG, sine_arriving()), LOOPBACK, OscilloscopeParams(**BASE), n=4)

    assert len(ups) == 4 and time.monotonic() - t0 >= 3 * Oscilloscope.MIN_REDRAW_S
    assert Oscilloscope.MIN_REDRAW_S == pytest.approx(0.2)
