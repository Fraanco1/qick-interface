"""Saves runs as data/<date>/<time>_<measurement>_<chip>.npz plus a .json with the same name."""
import json
import re
from datetime import datetime
from importlib.metadata import version
from pathlib import Path

import numpy as np

from .measurements.base import Update


def save_run(data_dir: Path, measurement: str, profile, params, update: Update,
             completed: bool) -> str:
    """Write the run's arrays and metadata; returns the path relative to data_dir, without suffix."""
    now = datetime.now()
    chip = re.sub(r"[^\w.-]+", "_", profile.chip)
    rel = Path(now.strftime("%Y-%m-%d")) / f"{now:%H%M%S}_{measurement}_{chip}"
    n = 2
    while (data_dir / f"{rel}.json").exists():  # two runs in the same second
        rel = rel.with_name(f"{now:%H%M%S}_{measurement}_{chip}_{n}")
        n += 1
    (data_dir / rel).parent.mkdir(parents=True, exist_ok=True)

    np.savez(data_dir / f"{rel}.npz", x=update.x, **update.traces, **update.raw)
    (data_dir / f"{rel}.json").write_text(json.dumps({
        "measurement": measurement,
        "saved_at": now.isoformat(timespec="seconds"),
        "completed": completed,
        "rounds_done": update.round,
        "rounds": update.rounds,
        "profile": profile.model_dump(),
        "params": params.model_dump(),
        "arrays": ["x", *update.traces, *update.raw],
        "versions": {"qick": version("qick"), "qick-interface": version("qick-interface")},
    }, indent=2))
    return rel.as_posix()
