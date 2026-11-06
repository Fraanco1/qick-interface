"""The external LO: a Keysight signal generator (our EXG N5173B, or a CXG N5166B), over LAN with SCPI on port 5025.

Before each run or output tone the app makes the generator match the setup: CW (modulation off), the
setup's frequency and power, RF on. It reads the instrument first and only changes what differs, then
waits for it (*OPC?) and checks its error queue. RF stays on between runs. The frequency and power range
are the generator's own, read when it first answers; the power also stops at MAX_DBM, the mixers' limit.
"""
from .scpi import ScpiError, ScpiInstrument


class LoError(ScpiError):
    """The LO can't be set as the setup asks, or doesn't answer."""


class _ConnectionLost(LoError):
    pass


class KeysightLo(ScpiInstrument):
    Error, Lost, what = LoError, _ConnectionLost, "the LO"
    MAX_DBM = 16.0  # the MMIQ-0416LS mixers take 7-16 dBm of LO (docs/research/mixer-mmiq-0416ls.md)

    def __init__(self, host: str, port: int = 5025, timeout_s: float = 5.0):
        super().__init__(host, port, timeout_s)
        self._limits = None  # (model, MHz range, dBm range), read from the generator when it first answers

    def apply(self, freq_mhz: float, power_dbm: float) -> dict:
        """Make the LO output a CW tone at freq_mhz and power_dbm; returns what it reads back."""
        try:
            return self._apply(freq_mhz, power_dbm)
        except _ConnectionLost:  # instruments may drop an idle connection: reconnect once
            return self._apply(freq_mhz, power_dbm)

    def _check(self, freq_mhz, power_dbm):
        if self._limits is None:
            model = self._query("*IDN?").split(",")[1].strip()
            mhz = tuple(float(self._query(f":FREQ? {m}")) / 1e6 for m in ("MIN", "MAX"))
            dbm = tuple(float(self._query(f":POW? {m}")) for m in ("MIN", "MAX"))
            self._limits = model, mhz, dbm
        model, (f_min, f_max), (p_min, p_max) = self._limits
        if not f_min <= freq_mhz <= f_max:
            raise LoError(f"The {model} reaches {f_min * 1e3:g} kHz to {f_max:.0f} MHz; the setup asks for an LO "
                          f"of {freq_mhz:g} MHz.")
        if power_dbm > self.MAX_DBM:
            raise LoError(f"The LO power stops at {self.MAX_DBM:g} dBm, the mixers' limit; the setup asks for "
                          f"{power_dbm:g} dBm.")
        if not p_min <= power_dbm <= p_max:
            raise LoError(f"The {model}'s power goes from {p_min:g} to {p_max:g} dBm; the setup asks for "
                          f"{power_dbm:g} dBm.")
        return model

    def _apply(self, freq_mhz, power_dbm):
        model = self._check(freq_mhz, power_dbm)
        now = self.read()
        if self._query(":OUTP:MOD?") != "0":
            self._send(":OUTP:MOD OFF")
        if abs(now["freq_mhz"] - freq_mhz) > 1e-6:
            self._send(f":FREQ {freq_mhz:.9f} MHZ")
        if abs(now["power_dbm"] - power_dbm) > 0.005:
            self._send(f":POW {power_dbm:.2f} DBM")
        if not now["on"]:
            self._send(":OUTP ON")
        self._query("*OPC?")  # wait until the instrument has settled
        self._check_errors(model)
        return self.read()

    def read(self) -> dict:
        return {"freq_mhz": round(float(self._query(":FREQ?")) / 1e6, 9),
                "power_dbm": round(float(self._query(":POW?")), 2),
                "on": self._query(":OUTP?") == "1"}
