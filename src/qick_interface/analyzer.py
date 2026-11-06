"""The signal analyzer: a Keysight X-series (our PXA N9032B), over LAN with SCPI on port 5025.

Used to read the power of a CW tone: prepare() sets a narrow span around each frequency, single sweeps,
clear/write trace (Max Hold would keep returning old peaks), auto RBW and attenuation and a reference level
above anything the DACs can reach; peak_dbm(f) centres there, sweeps once and reads the peak marker, which
must lie within the span; release() puts back the trace mode it found and lets the analyzer sweep again.
"""
from .scpi import ScpiError, ScpiInstrument


class AnalyzerError(ScpiError):
    """The analyzer can't measure as asked, or doesn't answer."""


class _ConnectionLost(AnalyzerError):
    pass


class KeysightAnalyzer(ScpiInstrument):
    Error, Lost, what = AnalyzerError, _ConnectionLost, "the signal analyzer"
    SPAN_MHZ = 1.0
    REF_LEVEL_DBM = 10.0  # a DAC at full scale gives about −1 dBm

    def __init__(self, host: str, port: int = 5025, timeout_s: float = 10.0):
        super().__init__(host, port, timeout_s)
        self._model = None
        self._trace_type = None  # what trace 1 was set to before prepare()

    @property
    def model(self) -> str:
        if self._model is None:
            self._model = self._query("*IDN?").split(",")[1].strip()
        return self._model

    def prepare(self) -> None:
        self._send(":INST:SEL SA")
        self._trace_type = self._query(":TRAC1:TYPE?")
        for command in (":INIT:CONT OFF", ":TRAC1:TYPE WRIT", ":AVER:STAT OFF", f":FREQ:SPAN {self.SPAN_MHZ} MHZ",
                        ":BAND:AUTO ON", ":POW:ATT:AUTO ON", f":DISP:WIND:TRAC:Y:RLEV {self.REF_LEVEL_DBM} DBM",
                        ":CALC:MARK1:MODE POS", ":CALC:MARK1:TRAC 1"):
            self._send(command)
        self._query("*OPC?")
        self._check_errors(self.model)

    def peak_dbm(self, f_mhz: float) -> float:
        """The highest point within the span around f_mhz, in dBm at the analyzer's input."""
        self._send(f":FREQ:CENT {f_mhz:.6f} MHZ")
        self._send(":INIT:IMM")
        self._query("*OPC?")  # the sweep is done
        self._send(":CALC:MARK1:MAX")
        at_mhz = float(self._query(":CALC:MARK1:X?")) / 1e6
        if abs(at_mhz - f_mhz) > self.SPAN_MHZ / 2:
            raise AnalyzerError(f"The {self.model}'s peak marker is at {at_mhz:.1f} MHz, outside the span around "
                                f"{f_mhz:g} MHz; check the analyzer's trace and marker settings.")
        return float(self._query(":CALC:MARK1:Y?"))

    def release(self) -> None:
        if self._trace_type:
            self._send(f":TRAC1:TYPE {self._trace_type}")
        self._send(":INIT:CONT ON")
        self._query("*OPC?")  # done before the caller moves on
