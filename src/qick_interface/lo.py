"""The external LO: a Keysight N5166B CXG (option 506, 9 kHz to 6 GHz), over LAN with SCPI on port 5025.

Before each run or output tone the app makes the CXG match the setup: CW (modulation off), the setup's
frequency and power, RF on. It reads the instrument first and only changes what differs, then waits
for the instrument (*OPC?) and checks its error queue. RF stays on between runs.
"""
import socket


class LoError(RuntimeError):
    """The LO can't be set as the setup asks, or doesn't answer."""


class _ConnectionLost(LoError):
    pass


class CxgLo:
    MIN_MHZ, MAX_MHZ = 0.009, 6000.0
    MIN_DBM, MAX_DBM = -110.0, 18.0

    def __init__(self, host: str, port: int = 5025, timeout_s: float = 5.0):
        self._address, self._timeout = (host, port), timeout_s
        self._sock = None

    def apply(self, freq_mhz: float, power_dbm: float) -> dict:
        """Make the LO output a CW tone at freq_mhz and power_dbm; returns what it reads back."""
        if not self.MIN_MHZ <= freq_mhz <= self.MAX_MHZ:
            raise LoError(f"The CXG reaches 9 kHz to {self.MAX_MHZ:.0f} MHz; the setup asks for an LO "
                          f"of {freq_mhz:g} MHz.")
        if not self.MIN_DBM <= power_dbm <= self.MAX_DBM:
            raise LoError(f"The CXG's power goes from {self.MIN_DBM:g} to {self.MAX_DBM:g} dBm; "
                          f"the setup asks for {power_dbm:g} dBm.")
        try:
            return self._apply(freq_mhz, power_dbm)
        except _ConnectionLost:  # instruments may drop an idle connection: reconnect once
            return self._apply(freq_mhz, power_dbm)

    def _apply(self, freq_mhz, power_dbm):
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
        error = self._query(":SYST:ERR?")
        if not error.startswith(("+0", "0")):
            raise LoError(f"The CXG reports: {error}")
        return self.read()

    def read(self) -> dict:
        return {"freq_mhz": round(float(self._query(":FREQ?")) / 1e6, 9),
                "power_dbm": round(float(self._query(":POW?")), 2),
                "on": self._query(":OUTP?") == "1"}

    # --- SCPI over a socket: one command per line ------------------------------
    def _send(self, command: str) -> None:
        try:
            self._connection().sendall((command + "\n").encode())
        except OSError as e:
            self._drop(e)

    def _query(self, command: str) -> str:
        self._send(command)
        try:
            reply = self._file.readline()
        except OSError as e:
            self._drop(e)
        if not reply:
            self._drop(ConnectionError("connection closed"))
        return reply.strip()

    def _connection(self):
        if self._sock is None:
            try:
                self._sock = socket.create_connection(self._address, timeout=self._timeout)
            except OSError as e:
                raise LoError(f"No answer from the LO at {self._address[0]}:{self._address[1]} ({e}).") from e
            self._file = self._sock.makefile("r", newline="\n")
        return self._sock

    def _drop(self, error):
        """Forget a broken connection (the next call reconnects) and report it."""
        if self._sock is not None:
            self._sock.close()
        self._sock = None
        raise _ConnectionLost(f"Lost the connection to the LO at {self._address[0]} ({error}).") from error
