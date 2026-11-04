"""RX I/Q calibration: measures the imbalance of the I/Q return path (mixer, I and Q cables, ADC paths).

An ideal I/Q mixer gives Y_Q = −j·Y_I on the upper sideband (+j·Y_I on the lower). The measured ratio
r = Y_Q / (∓j·Y_I) is fitted with g·e^{j(φ + 2π·f_IF·τ)}: a gain ratio g, a phase offset φ, and a delay τ
between the two paths. Everything before the mixer (chip, lines, amplifiers, LO) multiplies I and Q
alike and cancels in r, so it can be measured with the chip in place. Calibrate an I/Q output first:
its image would otherwise bias r. See docs/s21.md.
"""
from collections.abc import Callable, Iterator

import numpy as np
from pydantic import Field

from ..profiles import SetupProfile
from .base import Update
from .resonator_sweep import ResonatorSweep, ResonatorSweepParams


class RxIqCalParams(ResonatorSweepParams):
    points: int = Field(41, ge=3, le=10001, title="Points", json_schema_extra={"group": "Sweep"})


class RxIqCal:
    name = "RX I/Q calibration"
    Params = RxIqCalParams
    x_axis = {"title": "Frequency", "unit": "MHz"}
    plots = [{"title": "Q/I gain", "unit": "dB", "traces": ["Q/I gain (dB)", "Gain fit (dB)"]},
             {"title": "Q phase error", "unit": "°", "traces": ["Q phase (°)", "Phase fit (°)"]}]
    marker_sets = None
    info_sets = {}
    setup_sets = {"Q/I gain": "rx_gain_ratio", "Q phase (°)": "rx_phase_deg", "I/Q delay (ps)": "rx_delay_ps"}
    setup_label = "RX calibration"

    @classmethod
    def run(cls, board, profile: SetupProfile, params: RxIqCalParams,
            should_stop: Callable[[], bool] = lambda: False) -> Iterator[Update]:
        if profile.return_path != "iq":
            raise ValueError("RX I/Q calibration needs a setup whose Return path is I/Q.")
        program, if_mhz, rf = ResonatorSweep.program(board, profile, params)
        sideband = -1 if profile.lo_mhz is not None and profile.sideband == "lower" else 1

        for i, iq in enumerate(board.run(program, params.rounds, should_stop), start=1):
            y_i, y_q = iq[0], iq[1]
            fit = _fit(if_mhz, y_q / (-sideband * 1j * y_i), weights=np.abs(y_i))
            yield Update(i, params.rounds, rf, {
                "Q/I gain (dB)": 20 * np.log10(np.abs(fit["r"])),
                "Gain fit (dB)": np.full(rf.size, 20 * np.log10(fit["gain"])),
                "Q phase (°)": np.degrees(fit["phase"]),
                "Phase fit (°)": np.degrees(fit["phase_fit"]),
            }, raw={"y_i": y_i, "y_q": y_q, "if_mhz": if_mhz}, info={
                "Q/I gain": fit["gain"],
                "Q phase (°)": fit["phase0_deg"],
                "I/Q delay (ps)": fit["delay_ps"],
                "Image rejection (dB)": fit["rejection_db"],
            })


def _fit(if_mhz, r, weights):
    """g = weighted mean |r|; phase of r = φ + 2π·f·τ by a weighted straight line. The scatter left
    over estimates the image rejection after correction: image/signal ≈ (δg² + δφ²)/4."""
    gain = np.average(np.abs(r), weights=weights)
    phase = np.unwrap(np.angle(r))
    slope, offset = np.polyfit(if_mhz, phase, 1, w=weights)
    phase_fit = slope * if_mhz + offset
    dg = np.sqrt(np.average((np.abs(r) / gain - 1) ** 2, weights=weights))
    dphi = np.sqrt(np.average((phase - phase_fit) ** 2, weights=weights))
    return {"r": r, "gain": gain, "phase": phase, "phase_fit": phase_fit,
            "phase0_deg": np.degrees(np.angle(np.exp(1j * offset))),
            "delay_ps": slope / (2 * np.pi) * 1e6,  # rad/MHz → ps
            "rejection_db": -10 * np.log10(max((dg ** 2 + dphi ** 2) / 4, 1e-12))}
