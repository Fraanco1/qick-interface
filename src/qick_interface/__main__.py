"""Start the instrument: python -m qick_interface [--fake] [--host 0.0.0.0] [--port 8080]"""
import argparse
from pathlib import Path

import numpy as np
import uvicorn

from .board import FakeBoard, QickBoard
from .server import create_app

FIXTURE = Path(__file__).resolve().parents[2] / "tests" / "fixtures" / "soccfg_rfsoc4x2.json"


def simulated_chip(program):
    """For --fake: a resonator dip, or a qubit dip in two-tone, in the middle of the sweep, plus noise."""
    if "qubit" in program.pulses:
        from .measurements.two_tone import TwoTone
        f = TwoTone.qubit_if_axis(program)
        f0, width = (f[0] + f[-1]) / 2, max(abs(f[-1] - f[0]) / 60, 0.01)
        s21 = 800 * (1 - 0.3 / (1 + ((f - f0) / width) ** 2)) * np.exp(0.4j / (1 + ((f - f0) / width) ** 2))
    else:
        from .measurements.resonator_sweep import ResonatorSweep
        f = ResonatorSweep.if_axis(program)
        f0, width = (f[0] + f[-1]) / 2, max(abs(f[-1] - f[0]) / 40, 0.01)
        s21 = 800 * (1 - 0.85 / (1 + 2j * (f - f0) / width)) * np.exp(-2j * np.pi * f * 0.05)
    return [s21 + np.random.normal(0, 4, (f.size, 2)) @ [1, 1j]]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fake", action="store_true", help="simulate the board (no hardware)")
    parser.add_argument("--board", default="192.168.3.1", help="QICK Pyro4 nameserver address")
    parser.add_argument("--host", default="0.0.0.0", help="address to serve the page on")
    parser.add_argument("--port", type=int, default=8080)
    parser.add_argument("--data", type=Path, default=Path("data"))
    parser.add_argument("--profiles", type=Path, default=Path("profiles"))
    args = parser.parse_args()

    if args.fake:
        from qick import QickConfig
        board = FakeBoard(QickConfig(str(FIXTURE)), simulated_chip, round_time_s=0.3)
    else:
        board = QickBoard(host=args.board)
    uvicorn.run(create_app(board, args.data, args.profiles), host=args.host, port=args.port)


if __name__ == "__main__":
    main()
