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
