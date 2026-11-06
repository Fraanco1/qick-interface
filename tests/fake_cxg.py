"""A stand-in for a Keysight signal generator on localhost: SCPI over a plain socket, one command per line.
By default an N5166B CXG (9 kHz to 6 GHz, up to +18 dBm); pass another model and range for e.g. the EXG."""
import socket
import threading


class FakeCxg:
    def __init__(self, model="N5166B", freq_range_hz=(9e3, 6e9), power_range_dbm=(-110.0, 18.0)):
        self.model, self.freq_range_hz, self.power_range_dbm = model, freq_range_hz, power_range_dbm
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
            return f"Keysight Technologies,{self.model},MY00000000,B.01.00"
        if head == ":FREQ?" and arg:
            return f"{self.freq_range_hz[arg.upper() == 'MAX']:+.14E}"
        if head == ":POW?" and arg:
            return f"{self.power_range_dbm[arg.upper() == 'MAX']:+.8E}"
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
