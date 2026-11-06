"""SCPI over a LAN socket (port 5025), one command per line: shared by the LO and the signal analyzer."""
import socket


class ScpiError(RuntimeError):
    """The instrument can't do what is asked, or doesn't answer."""


class ScpiInstrument:
    Error = ScpiError  # raised when the instrument can't be reached
    Lost = ScpiError   # raised when a connection breaks (the next call reconnects)
    what = "instrument"  # for messages: "the LO", "the signal analyzer"

    def __init__(self, host: str, port: int = 5025, timeout_s: float = 5.0):
        self._address, self._timeout = (host, port), timeout_s
        self._sock = None

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

    def _check_errors(self, model: str) -> None:
        error = self._query(":SYST:ERR?")
        if not error.startswith(("+0", "0")):
            raise self.Error(f"The {model} reports: {error}")

    def _connection(self):
        if self._sock is None:
            try:
                self._sock = socket.create_connection(self._address, timeout=self._timeout)
            except OSError as e:
                raise self.Error(f"No answer from {self.what} at {self._address[0]}:{self._address[1]} ({e}).") from e
            self._file = self._sock.makefile("r", newline="\n")
        return self._sock

    def _drop(self, error):
        """Forget a broken connection (the next call reconnects) and report it."""
        if self._sock is not None:
            self._sock.close()
        self._sock = None
        raise self.Lost(f"Lost the connection to {self.what} at {self._address[0]} ({error}).") from error
