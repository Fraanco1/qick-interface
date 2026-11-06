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


class FakeIqMixer:
    """For --fake and tests: an I/Q mixer whose RF output is cabled to a signal analyzer. The Q DAC runs
    q_lead_ps ahead of the I DAC; the mixer adds phase_error_deg(f) and gain_error(f) on Q at IF f (MHz).
    The upper sideband (LO + f) is |I + Q·e^{j(θ−90°)}|/2 and the lower |I + Q·e^{j(θ+90°)}|/2, θ the Q−I
    phase at the mixer: Q at +90° gives the upper sideband. lo_mhz: a frequency, or a FakeLo to follow.
    direct: an analyzer for what is not an I/Q pair (a single DAC cabled straight to it)."""
    model = "N9032B (simulated)"

    def __init__(self, board, lo_mhz, i_dac="DAC_A", q_dac="DAC_B", q_lead_ps=0.0,
                 phase_error_deg=lambda f: 0.0, gain_error=lambda f: 1.0, dbm_at=lambda f: -10.0,
                 lo_leakage_dbm=-56.0, direct=None):
        self._board, self._lo_source, self._direct = board, lo_mhz, direct
        self._i, self._q = gen_channel(board.soccfg, i_dac), gen_channel(board.soccfg, q_dac)
        self._lead, self._phase_error, self._gain_error = q_lead_ps, phase_error_deg, gain_error
        self._dbm_at, self._leak = dbm_at, lo_leakage_dbm

    def prepare(self) -> None:
        pass

    def release(self) -> None:
        pass

    def _tone(self, gen):
        program = self._board.playing
        for name, pulse in (program.pulses.items() if program is not None else []):
            if pulse.gen_chs[0] == gen:
                return (program.get_pulse_param(name, "freq"), program.get_pulse_param(name, "gain"),
                        program.get_pulse_param(name, "phase"))
        return None

    @property
    def _lo(self) -> float:
        return getattr(self._lo_source, "freq_mhz", self._lo_source)

    def peak_dbm(self, f_mhz: float) -> float:
        i, q = self._tone(self._i), self._tone(self._q)
        if self._direct is not None and (i is None or q is None):
            return self._direct.peak_dbm(f_mhz)
        floor = 10 ** (NOISE_FLOOR_DBM / 10)
        power = floor + (10 ** (self._leak / 10) if abs(f_mhz - self._lo) < 0.5 else 0.0)
        if i is not None and q is not None:
            f = i[0]
            theta = np.radians(q[2] - i[2] + 360e-6 * f * self._lead + self._phase_error(f))
            a_q = q[1] * self._gain_error(f)
            for rf, turn in ((self._lo + f, -np.pi / 2), (self._lo - f, np.pi / 2)):
                if abs(rf - f_mhz) < 0.5:
                    amp = abs(i[1] + a_q * np.exp(1j * (theta + turn))) / 2
                    power += 10 ** ((self._dbm_at(f) + 20 * np.log10(max(amp, 1e-9))) / 10)
        return float(10 * np.log10(power))


class FakeLo:
    """For --fake: an LO that keeps what it was set to."""

    def __init__(self, freq_mhz: float = 6000.0, power_dbm: float = 13.0):
        self.freq_mhz, self.power_dbm = freq_mhz, power_dbm

    def apply(self, freq_mhz: float, power_dbm: float) -> dict:
        self.freq_mhz, self.power_dbm = freq_mhz, power_dbm
        return self.read()

    def read(self) -> dict:
        return {"freq_mhz": self.freq_mhz, "power_dbm": self.power_dbm, "on": True}
