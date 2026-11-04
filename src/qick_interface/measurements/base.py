"""What every measurement produces while it runs."""
from dataclasses import dataclass, field

import numpy as np

from ..iq import rx_imbalance, tone_gain


@dataclass
class Update:
    """Data after one round of averaging: x axis plus one array per trace."""
    round: int
    rounds: int
    x: np.ndarray
    traces: dict[str, np.ndarray]
    raw: dict[str, np.ndarray] = field(default_factory=dict)  # saved, not plotted
    x_axis: dict | None = None  # overrides the measurement's default x axis, e.g. when the sweep type changes
    info: dict[str, float] = field(default_factory=dict)  # fit results shown next to the plot


def received_s21(iq: list[np.ndarray], program, tone: str, profile) -> np.ndarray:
    """The readouts' I+jQ as S21 (see docs/s21.md), divided by the tone's gain (as QICK rounded it) so the
    trace does not move with the power setting, like a PNA-X's b2/a1. Gain 0 gives gaps.

    Real return path: one readout; on the lower sideband (RF = LO − IF) the mixer mirrors the chip's
    phase, so it is conjugated. I/Q return path: readouts Y_I and Y_Q, with Y_Q corrected by the RX
    calibration; the upper sideband is Y_I + j·Y_Q, the lower conj(Y_I − j·Y_Q), and the other cancels."""
    lower = profile.lo_mhz is not None and profile.sideband == "lower"
    if profile.return_path == "iq":
        y_i = iq[0]
        y_q = iq[1] / rx_imbalance(profile, program.get_pulse_param(tone, "freq", as_array=True))
        s21 = np.conj(y_i - 1j * y_q) if lower else y_i + 1j * y_q
    else:
        s21 = np.conj(iq[0]) if lower else iq[0]
    with np.errstate(divide="ignore", invalid="ignore"):
        return s21 / tone_gain(program, tone)
