"""Board: the only module that talks to QICK hardware.

A Board exposes `soccfg` (to compile programs) and `run(program, rounds, should_stop)`,
which yields, after each round, the running average for each readout of the program
as complex arrays shaped like the program's loops.
"""
import time
from collections.abc import Callable, Iterator

import numpy as np
import Pyro4
import qick
from qick import QickConfig


class FakeBoard:
    """Simulated board: `simulate(program)` returns one complex array per readout."""

    def __init__(self, soccfg, simulate: Callable, round_time_s: float = 0.0):
        self.soccfg = soccfg
        self._simulate = simulate
        self._round_time_s = round_time_s

    def run(self, program, rounds: int, should_stop: Callable[[], bool] = lambda: False
            ) -> Iterator[list[np.ndarray]]:
        result = self._simulate(program)
        for _ in range(rounds):
            if should_stop():
                return
            time.sleep(self._round_time_s)
            yield result


class QickBoard:
    """The real board, reached through the QICK Pyro4 server (board/qick_service.py)."""

    CALL_TIMEOUT_S = 30  # a stuck board raises instead of hanging the app

    def __init__(self, host: str = "192.168.3.1", port: int = 8888, name: str = "rfsoc"):
        Pyro4.config.SERIALIZER = "pickle"
        Pyro4.config.PICKLE_PROTOCOL_VERSION = 4
        self._soc = Pyro4.Proxy(Pyro4.locateNS(host=host, port=port).lookup(name))
        self._soc._pyroTimeout = self.CALL_TIMEOUT_S
        self.soccfg = QickConfig(self._soc.get_cfg())
        if self.soccfg["sw_version"] != qick.__version__:
            raise RuntimeError(f"QICK version mismatch: board {self.soccfg['sw_version']}, "
                               f"PC {qick.__version__}. Install the same version on both.")

    def run(self, program, rounds: int, should_stop: Callable[[], bool] = lambda: False
            ) -> Iterator[list[np.ndarray]]:
        try:
            program.acquire(self._soc, rounds=rounds, progress=False, step_rounds=True)
            while True:
                more = program.finish_round()
                means = program._summarize_accumulated(program.rounds_buf)
                yield [m[0].dot([1, 1j]) for m in means]  # first read of each shot
                if not more or should_stop():
                    return
                program.prepare_round()
        except BaseException:  # includes GeneratorExit when the caller stops early
            self._abort()
            raise
        finally:
            self._quietly(self._soc.reset_gens)  # silence any output left playing

    def _abort(self):
        self._quietly(self._soc.stop_tproc)

    @staticmethod
    def _quietly(call):
        """Cleanup calls must not hide the error that caused them."""
        try:
            call()
        except Exception:
            pass


def gen_channel(soccfg, port: str) -> int:
    """QICK generator index for a board port label such as "DAC_B"."""
    return _channel(soccfg, "gens", soccfg._describe_dac, "dac", port)


def readout_channel(soccfg, port: str) -> int:
    """QICK readout index for a board port label such as "ADC_D"."""
    return _channel(soccfg, "readouts", soccfg._describe_adc, "adc", port)


def _channel(soccfg, kind, describe, key, port):
    for ch, cfg in enumerate(soccfg[kind]):
        if describe(cfg[key]).endswith(f"is {port}"):
            return ch
    raise ValueError(f"The board firmware has no {kind[:-1]} on port {port}.")
