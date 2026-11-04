"""What every measurement produces while it runs."""
from dataclasses import dataclass, field

import numpy as np

from ..iq import tone_gain


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


def received_s21(iq: np.ndarray, program, tone: str, profile) -> np.ndarray:
    """The readout's I+jQ as S21: divided by the tone's gain (as QICK rounded it), so the trace does not
    move with the power setting, like a PNA-X's b2/a1; and conjugated on the lower sideband, where a
    mixer delivers the chip's phase mirrored (RF = LO − IF). Gain 0 gives non-finite values (gaps)."""
    gain = tone_gain(program, tone)
    with np.errstate(divide="ignore", invalid="ignore"):
        s21 = iq / gain
    lower = profile.lo_mhz is not None and profile.sideband == "lower"
    return np.conj(s21) if lower else s21
