"""Board: the only module that talks to QICK hardware.

A Board exposes `soccfg` (to compile programs) and `run(program, rounds, should_stop, average)`,
which yields, after each round, one complex array per readout of the program, shaped like the
program's loops: the running average over the rounds so far, or with average=False that round
alone. rounds=None repeats until should_stop() says so.
"""
import itertools
import time
from collections.abc import Callable, Iterator

import numpy as np
import Pyro4
import qick
from qick import QickConfig

from .power import BoardCalibration


class FakeBoard:
    """Simulated board: `simulate(program)` returns one complex array per readout."""

    def __init__(self, soccfg, simulate: Callable, round_time_s: float = 0.0):
        self.soccfg = soccfg
        self.calibration = BoardCalibration()  # power scales of the converters; the app loads board.json
        self._simulate = simulate
        self._round_time_s = round_time_s
        self.playing = None  # program left playing by play(), for tests

    def capture(self, program) -> list[np.ndarray]:
        """The window's samples, averaged over the shots: one complex array per readout."""
        return self._simulate(program)

    def play(self, program) -> None:
        self.playing = program

    def silence(self) -> None:
        self.playing = None

    def run(self, program, rounds: int | None, should_stop: Callable[[], bool] = lambda: False,
            average: bool = True) -> Iterator[list[np.ndarray]]:
        result = self._simulate(program)
        for done in itertools.count(1):
            if should_stop() or (rounds is not None and done > rounds):
                return
            time.sleep(self._round_time_s)
            yield result if average or done == 1 else self._simulate(program)


class QickBoard:
    """The real board, reached through the QICK Pyro4 server (board/qick_service.py)."""

    CALL_TIMEOUT_S = 30  # a stuck board raises instead of hanging the app
    STALL_S = 30         # no data for this long during a round: give up with an error

    def __init__(self, host: str = "192.168.3.1", port: int = 8888, name: str = "rfsoc"):
        Pyro4.config.SERIALIZER = "pickle"
        Pyro4.config.PICKLE_PROTOCOL_VERSION = 4
        self._ns = Pyro4.locateNS(host=host, port=port)
        self._soc = Pyro4.Proxy(self._ns.lookup(name))
        self._soc._pyroTimeout = self.CALL_TIMEOUT_S
        self.soccfg = QickConfig(self._soc.get_cfg())
        self.calibration = BoardCalibration()  # power scales of the converters; the app loads board.json
        if self.soccfg["sw_version"] != qick.__version__:
            raise RuntimeError(f"QICK version mismatch: board {self.soccfg['sw_version']}, "
                               f"PC {qick.__version__}. Install the same version on both.")

    def run(self, program, rounds: int | None, should_stop: Callable[[], bool] = lambda: False,
            average: bool = True) -> Iterator[list[np.ndarray]]:
        try:
            # loads, prepares round 1; QICK uses `rounds` only for its progress bar
            program.acquire(self._soc, rounds=rounds or 1, progress=False, step_rounds=True)
            for done in itertools.count(1):
                self._acquire_round(program)
                if average:
                    data = program._summarize_accumulated(program.rounds_buf)
                else:
                    data = program.rounds_buf.pop()  # memory stays flat however long it runs
                yield [m[0].dot([1, 1j]) for m in data]  # first read of each shot
                if done == rounds or should_stop():
                    return
                program.prepare_round()
        except BaseException:  # includes GeneratorExit when the caller stops early
            self._abort()
            raise
        finally:
            self._quietly(self._soc.reset_gens)  # silence any output left playing

    def scope(self):
        """The oscilloscope the board service shares as "scope" (board/scope.py), or None without one.
        It has query(), write() and waveform(channel); a scope on the PC would offer the same."""
        try:
            return Pyro4.Proxy(self._ns.lookup("scope"))
        except Pyro4.errors.NamingError:
            return None

    def capture(self, program) -> list[np.ndarray]:
        """The window's samples, averaged over the shots: one complex array per readout."""
        try:
            data = program.acquire_decimated(self._soc, rounds=program.cfg.get("rounds", 1), progress=False)
            # with several shots per round QICK returns each shot: (shots, samples, I/Q)
            return [np.asarray(d).reshape(-1, *np.shape(d)[-2:]).mean(axis=0).dot([1, 1j]) for d in data]
        except BaseException:
            self._abort()
            raise
        finally:
            self._quietly(self._soc.reset_gens)

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
        """Start a program without waiting for it: a scope sequence keeps running, a periodic
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
