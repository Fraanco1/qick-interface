"""Setup profiles: the saved wiring of one chip (see GLOSSARY.md)."""
import re
from pathlib import Path
from typing import Literal

from pydantic import BaseModel


class SetupProfile(BaseModel):
    chip: str
    chip_type: Literal["transmon", "fluxonium"]
    lo_mhz: float | None = None  # None: no mixer, RF = IF
    sideband: Literal["upper", "lower"] = "upper"  # upper: RF = LO + IF
    readout_dac: str = "DAC_B"  # board port labels
    readout_adc: str = "ADC_D"


def load_profiles(directory: Path) -> dict[str, SetupProfile]:
    return {p.stem: SetupProfile.model_validate_json(p.read_text())
            for p in sorted(directory.glob("*.json"))}


def save_profile(directory: Path, profile: SetupProfile) -> None:
    if not re.fullmatch(r"[\w .-]+", profile.chip) or profile.chip.startswith("."):
        raise ValueError("Chip names may only use letters, digits, spaces, '.', '_' and '-'.")
    directory.mkdir(parents=True, exist_ok=True)
    (directory / f"{profile.chip}.json").write_text(profile.model_dump_json(indent=2))
