"""A stand-in for the Keysight PXA N9032B on localhost: SCPI over a plain socket, one command per line.
level(center_mhz) gives the peak it reads; commands are kept in .commands."""
import socket
import threading


class FakePxa:
    def __init__(self, level, trace_type="WRIT", marker_x_mhz=None):
        self.level, self.center_mhz, self.continuous = level, 1000.0, True
        self.trace_type = trace_type      # "MAXH" keeps old peaks, like the lab PXA was left
        self.marker_x_mhz = marker_x_mhz  # None: the peak sits at the centre; a number: a marker stuck there
        self.commands = []
        self._server = socket.create_server(("127.0.0.1", 0))
        self.port = self._server.getsockname()[1]
        threading.Thread(target=self._serve, daemon=True).start()

    def _serve(self):
        while True:
            conn, _ = self._server.accept()
            with conn, conn.makefile("rw", newline="\n") as f:
                for line in f:
                    reply = self._handle(line.strip())
                    if reply is not None:
                        f.write(reply + "\n")
                        f.flush()

    def _handle(self, cmd):
        self.commands.append(cmd)
        head, _, arg = cmd.partition(" ")
        head = head.upper()
        if head == "*IDN?":
            return "Keysight Technologies,N9032B,MY00000000,A.34.06"
        if head == "*OPC?":
            return "1"
        if head == ":SYST:ERR?":
            return '+0,"No error"'
        if head == ":TRAC1:TYPE?":
            return self.trace_type
        if head == ":CALC:MARK1:X?":
            return f"{(self.marker_x_mhz or self.center_mhz) * 1e6:+.11E}"
        if head == ":CALC:MARK1:Y?":
            return f"{self.level(self.center_mhz):+.8E}"
        if head == ":FREQ:CENT":
            value, unit = arg.split()
            self.center_mhz = float(value) * {"HZ": 1e-6, "MHZ": 1, "GHZ": 1e3}[unit.upper()]
        elif head == ":TRAC1:TYPE":
            self.trace_type = arg.upper()
        elif head == ":INIT:CONT":
            self.continuous = arg.upper() in ("ON", "1")
        return None
