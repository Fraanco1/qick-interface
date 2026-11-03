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
        self.playing = None  # program left playing by play(), for tests

    def play(self, program) -> None:
        self.playing = program

    def silence(self) -> None:
        self.playing = None

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
    STALL_S = 30         # no data for this long during a round: give up with an error

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
            program.acquire(self._soc, rounds=rounds, progress=False, step_rounds=True)  # loads, prepares round 1
            for done in range(1, rounds + 1):
                self._acquire_round(program)
                means = program._summarize_accumulated(program.rounds_buf)
                yield [m[0].dot([1, 1j]) for m in means]  # first read of each shot
                if done == rounds or should_stop():
                    return
                program.prepare_round()
        except BaseException:  # includes GeneratorExit when the caller stops early
            self._abort()
            raise
        finally:
            self._quietly(self._soc.reset_gens)  # silence any output left playing

    def _acquire_round(self, program) -> None:
        """One round of accumulated data: QICK's finish_round (qick_asm.py, accumulated branch), but
        every wait on the board is finite. QICK's own loop waits forever (poll_data(timeout=None)), and
        a board-side call left waiting takes data from later runs, which then hang in turn."""
        total = int(np.prod(program.loop_dims))
        reads = [ro["trigs"] for ro in program.ro_chs.values()]
        self._soc.start_readout(total, counter_addr=program.counter_addr, ch_list=list(program.ro_chs),
                                reads_per_shot=reads)
        count, last_data = 0, time.monotonic()
        while count < total:
            for shots, (data, _stats) in self._soc.poll_data(totaltime=0.1, timeout=1.0):
                for ch, n_reads in enumerate(reads):
                    program.acc_buf[ch].reshape((-1, 2))[count * n_reads:(count + shots) * n_reads] = data[ch]
                count += shots
                last_data = time.monotonic()
            if time.monotonic() - last_data > self.STALL_S:
                raise RuntimeError(f"The board stopped sending data ({count} of {total} shots after "
                                   f"{self.STALL_S} s without new data). Check the board service.")
        self._soc.cleanup_round()
        program.rounds_buf.append(program._process_accumulated(program.acc_buf))

    def play(self, program) -> None:
        """Start a program without waiting for it: a pulse train keeps running, a periodic
        tone keeps playing after the program ends. Both last until silence()."""
        self.silence()
        program.run(self._soc)

    def silence(self) -> None:
        self._soc.stop_tproc()
        self._soc.reset_gens()

    def _abort(self):
        self._quietly(self._soc.stop_tproc)
        self._quietly(self._soc.streamer.stop_readout)

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
