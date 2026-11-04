"""A stand-in for the Keysight N5166B CXG on localhost: SCPI over a plain socket, one command per line."""
import socket
import threading


class FakeCxg:
    def __init__(self):
        self.freq_hz, self.power_dbm, self.output, self.modulation = 1e9, -20.0, False, True
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
            return "Keysight Technologies,N5166B,MY00000000,B.01.00"
        if head == "*OPC?":
            return "1"
        if head == ":SYST:ERR?":
            return '+0,"No error"'
        if head == ":FREQ?":
            return f"{self.freq_hz:+.14E}"
        if head == ":POW?":
            return f"{self.power_dbm:+.8E}"
        if head == ":OUTP?":
            return "1" if self.output else "0"
        if head == ":OUTP:MOD?":
            return "1" if self.modulation else "0"
        if head == ":FREQ":
            value, unit = arg.split()
            self.freq_hz = float(value) * {"HZ": 1, "MHZ": 1e6, "GHZ": 1e9}[unit.upper()]
        elif head == ":POW":
            self.power_dbm = float(arg.split()[0])
        elif head == ":OUTP":
            self.output = arg.upper() in ("ON", "1")
        elif head == ":OUTP:MOD":
            self.modulation = arg.upper() in ("ON", "1")
        return None
