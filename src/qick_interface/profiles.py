"""Setup profiles: the saved wiring of one chip (see GLOSSARY.md)."""
import re
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class SetupProfile(BaseModel):
    model_config = ConfigDict(extra="forbid")  # a typo in a saved profile must not be ignored

    chip: str
    chip_type: Literal["transmon", "fluxonium"]
    lo_mhz: float | None = None  # None: no mixer, RF = IF
    sideband: Literal["upper", "lower"] = "upper"  # upper: RF = LO + IF
    output_path: Literal["real", "iq"] = "real"
    readout_dac: str = "DAC_B"  # board port labels; used by the real output path
    readout_adc: str = "ADC_D"
    i_dac: str = "DAC_A"  # used by the I/Q output path
    q_dac: str = "DAC_B"
    iq_phase_deg: float = Field(90.0, ge=0, le=180)  # Q phase relative to I, from calibration
    iq_gain_ratio: float = Field(1.0, gt=0, le=2)    # Q gain / I gain, from calibration


def load_profiles(directory: Path) -> dict[str, SetupProfile]:
    return {p.stem: SetupProfile.model_validate_json(p.read_text())
            for p in sorted(directory.glob("*.json"))}


def save_profile(directory: Path, profile: SetupProfile) -> None:
    if not re.fullmatch(r"[\w .-]+", profile.chip) or profile.chip.startswith("."):
        raise ValueError("Chip names may only use letters, digits, spaces, '.', '_' and '-'.")
    directory.mkdir(parents=True, exist_ok=True)
    (directory / f"{profile.chip}.json").write_text(profile.model_dump_json(indent=2))
