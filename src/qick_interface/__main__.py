"""Start the instrument: python -m qick_interface [--fake] [--host 0.0.0.0] [--port 8080]"""
import argparse
import time
from pathlib import Path

import numpy as np
import uvicorn

from .board import FakeBoard, QickBoard
from .fake_scope import FakeScope
from .lo import CxgLo
from .server import create_app

FIXTURE = Path(__file__).resolve().parents[2] / "tests" / "fixtures" / "soccfg_rfsoc4x2.json"


def simulated_chip(program):
    """For --fake: a resonator dip, a qubit dip in two-tone, Rabi oscillations, or a slowly
    drifting CW Time trace, plus noise; or a test pulse arriving 0.29 µs after it was sent."""
    if program.cfg.get("time_of_flight"):
        t = np.arange(int(program.cfg["window_us"] * 552.96)) / 552.96
        pulse = 900 * ((t >= 0.29) & (t < 0.29 + program.cfg["pulse_us"])) * np.exp(1.1j)
        return [pulse + np.random.normal(0, 4, (t.size, 2)) @ [1, 1j] for _ in program.ro_chs]
    if program.cfg.get("cw_time"):  # a 2 Hz wobble in level and phase over the sweep
        t_s = time.time() + np.arange(program.cfg["points"]) * program.cfg["spacing"] * program.reps * 1e-6
        s21 = (700 + 20 * np.sin(2 * np.pi * 2 * t_s)) * np.exp(1j * (0.3 + 0.1 * np.cos(2 * np.pi * 2 * t_s)))
        f = t_s  # only its size is used below
    elif "sweep" in program.cfg:  # Rabi: pi pulse at gain 0.35, or 0.1 µs, decaying over 1 µs
        from .measurements.rabi import Rabi
        f = Rabi.x_values(program)
        x_pi, decay = (0.35, 5.0) if program.cfg["sweep"] == "amplitude" else (0.1, 1.0)
        excited = 0.5 - 0.5 * np.cos(np.pi * f / x_pi) * np.exp(-f / decay)
        s21 = (700 + 120 * excited) * np.exp(1j * (0.6 + 0.3 * excited))
    elif "qubit" in program.pulses:
        from .measurements.two_tone import TwoTone
        f = TwoTone.qubit_if_axis(program)
        f0, width = (f[0] + f[-1]) / 2, max(abs(f[-1] - f[0]) / 60, 0.01)
        s21 = 800 * (1 - 0.3 / (1 + ((f - f0) / width) ** 2)) * np.exp(0.4j / (1 + ((f - f0) / width) ** 2))
    else:
        from .measurements.resonator_sweep import ResonatorSweep
        f = ResonatorSweep.if_axis(program)
        f0, width = (f[0] + f[-1]) / 2, max(abs(f[-1] - f[0]) / 40, 0.01)
        s21 = 800 * (1 - 0.85 / (1 + 2j * (f - f0) / width)) * np.exp(-2j * np.pi * f * 0.05)
    tone = "probe" if "probe" in program.pulses else "readout"
    s21 = program.get_pulse_param(tone, "gain") * s21  # the signal scales with gain, the noise doesn't
    noise = lambda: np.random.normal(0, 4, (f.size, 2)) @ [1, 1j]
    if len(program.ro_chs) == 2:  # I/Q return through a slightly imbalanced mixer (upper sideband)
        imbalance = 0.95 * np.exp(1j * (np.radians(3.0) + 2 * np.pi * program.get_pulse_param(tone, "freq", as_array=True) * 30e-6))
        return [s21 / 2 + noise(), -1j * imbalance * s21 / 2 + noise()]
    return [s21 + noise()]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fake", action="store_true", help="simulate the board (no hardware)")
    parser.add_argument("--board", default="192.168.3.1", help="QICK Pyro4 nameserver address")
    parser.add_argument("--host", default="0.0.0.0", help="address to serve the page on")
    parser.add_argument("--port", type=int, default=8080)
    parser.add_argument("--data", type=Path, default=Path("data"))
    parser.add_argument("--profiles", type=Path, default=Path("profiles"))
    parser.add_argument("--lo", metavar="ADDRESS", help="IP address of the CXG LO; without it the LO is set by hand")
    args = parser.parse_args()

    if args.fake:
        from qick import QickConfig
        board = FakeBoard(QickConfig(str(FIXTURE)), simulated_chip, round_time_s=0.3)
        scope = FakeScope(board, {"DAC_A": ("CH1", 0.0), "DAC_B": ("CH3", 1550.0)})  # Q 1.55 ns ahead
    else:
        board = QickBoard(host=args.board)
        scope = board.scope()
    host, _, port = (args.lo or "").partition(":")
    lo = CxgLo(host, int(port or 5025)) if host else None
    uvicorn.run(create_app(board, args.data, args.profiles, lo, scope), host=args.host, port=args.port)


if __name__ == "__main__":
    main()
