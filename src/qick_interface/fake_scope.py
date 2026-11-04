"""For --fake and tests: an oscilloscope showing what a FakeBoard plays. Each DAC is cabled to a scope
channel and may run some time ahead of the others, like the real board's DAC tiles."""
import numpy as np

from .board import gen_channel

SAMPLE_S = 1e-9  # 1 GS/s, as the MSO2024B
POINTS = 4000
VOLTS_AT_FULL_GAIN = 0.6


class FakeScope:
    def __init__(self, board, wiring: dict[str, tuple[str, float]], noise_v: float = 0.002):
        """wiring: DAC port label -> (scope channel, how far that DAC runs ahead, in ps)."""
        self._board = board
        self._gens = {gen_channel(board.soccfg, port): (ch, lead_ps) for port, (ch, lead_ps) in wiring.items()}
        self._noise_v = noise_v
        self._rng = np.random.default_rng(0)
        self._settings = {}

    def write(self, command: str) -> None:
        key, _, value = command.partition(" ")
        self._settings[key] = value

    def query(self, command: str) -> str:
        if command == "ACQUIRE:STATE?":
            return "0"  # every acquisition is instant
        return self._settings.get(command.rstrip("?"), "0")

    def waveform(self, channel: str):
        t = np.arange(POINTS) * SAMPLE_S
        v = self._rng.normal(0, self._noise_v, POINTS)
        program = self._board.playing
        for name, pulse in (program.pulses.items() if program is not None else []):
            ch, lead_ps = self._gens.get(pulse.gen_chs[0], (None, 0.0))
            if ch != channel:
                continue
            f_hz = program.get_pulse_param(name, "freq") * 1e6
            phase = np.radians(program.get_pulse_param(name, "phase"))
            gain = program.get_pulse_param(name, "gain")
            v += gain * VOLTS_AT_FULL_GAIN * np.cos(2 * np.pi * f_hz * (t + lead_ps * 1e-12) + phase)
        return t, v
