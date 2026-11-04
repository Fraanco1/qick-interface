"""Runs on the RFSoC: the lab oscilloscope (Tektronix MSO2024B on the board's USB port), shared with
the lab PC over Pyro4 as "scope". Opened on first use, so the service starts without it."""
import numpy as np
import Pyro4
import pyvisa


@Pyro4.expose
class Scope:
    def __init__(self):
        self._inst = None

    def query(self, command: str) -> str:
        return self._call(lambda s: s.query(command).strip())

    def write(self, command: str) -> None:
        self._call(lambda s: s.write(command))

    def waveform(self, channel: str):
        """The channel's last acquisition: (time from the trigger in s, volts), as numpy arrays."""
        def read(s):
            s.write(f"DATA:SOURCE {channel};:DATA:ENCDG RIBINARY;:DATA:WIDTH 1;:DATA:START 1;:DATA:STOP 10000000")
            x_incr, x_zero, pt_off, y_mult, y_off, y_zero = (
                float(s.query(f"WFMOUTPRE:{k}?")) for k in ("XINCR", "XZERO", "PT_OFF", "YMULT", "YOFF", "YZERO"))
            raw = s.query_binary_values("CURVE?", datatype="b", is_big_endian=True, container=np.array)
            return x_zero + (np.arange(raw.size) - pt_off) * x_incr, (raw - y_off) * y_mult + y_zero
        return self._call(read)

    def _call(self, action):
        try:
            return action(self._open())
        except Exception:
            self._inst = None  # unplugged or confused: reopen on the next call
            raise

    def _open(self):
        if self._inst is None:
            rm = pyvisa.ResourceManager("@py")
            found = rm.list_resources("USB?*INSTR")
            if not found:
                raise RuntimeError("No oscilloscope on the board's USB port.")
            self._inst = rm.open_resource(found[0], timeout=20000)
            self._inst.write("HEADER OFF")
        return self._inst
