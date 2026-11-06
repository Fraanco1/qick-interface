"""For --fake and tests: a signal analyzer reading what a FakeBoard plays. Each DAC in `wiring` is cabled
to it through cable_loss_db; wiring maps the port label to its output at gain 1 against frequency (dBm)."""
import numpy as np

from .board import gen_channel

NOISE_FLOOR_DBM = -95.0


class FakeAnalyzer:
    model = "N9032B (simulated)"

    def __init__(self, board, wiring: dict, cable_loss_db: float = 0.0):
        self._board, self._loss = board, cable_loss_db
        self._ports = {gen_channel(board.soccfg, port): dbm_at for port, dbm_at in wiring.items()}

    def prepare(self) -> None:
        pass

    def release(self) -> None:
        pass

    def peak_dbm(self, f_mhz: float) -> float:
        program = self._board.playing
        for name, pulse in (program.pulses.items() if program is not None else []):
            dbm_at = self._ports.get(pulse.gen_chs[0])
            f = program.get_pulse_param(name, "freq")
            if dbm_at is not None and abs(f - f_mhz) < 0.5:
                gain = program.get_pulse_param(name, "gain")
                return float(dbm_at(f) + 20 * np.log10(gain) - self._loss)
        return NOISE_FLOOR_DBM
