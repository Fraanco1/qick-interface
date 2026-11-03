"""What every measurement produces while it runs."""
from dataclasses import dataclass, field

import numpy as np


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
