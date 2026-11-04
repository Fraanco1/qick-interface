"""Setup profiles: the saved wiring of one chip (see GLOSSARY.md)."""
import re
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


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
    return_path: Literal["real", "iq"] = "real"
    i_adc: str = "ADC_D"  # used by the I/Q return path
    q_adc: str = "ADC_C"
    # RX I/Q calibration: Y_Q = ∓j·g·e^{j(φ + 2π·f_IF·τ)}·Y_I through the real mixer and cables (see docs/s21.md)
    rx_gain_ratio: float = Field(1.0, gt=0, le=2)
    rx_phase_deg: float = Field(0.0, ge=-180, le=180)
    rx_delay_ps: float = 0.0
    # Electrical delay subtracted from resonator-sweep phases (stored from a wide sweep); None: fitted per sweep
    electrical_delay_ns: float | None = None
    # A separate line for the qubit tone, straight from its own DAC (no mixer: RF = DAC frequency)
    control_dac: Literal["DAC_A", "DAC_B"] | None = None

    @model_validator(mode="after")
    def _control_line_has_its_own_dac(self):
        used = {self.readout_dac} if self.output_path == "real" else {self.i_dac, self.q_dac}
        if self.control_dac in used:
            raise ValueError(f"The control line needs its own DAC; {self.control_dac} already carries the "
                             "readout output.")
        return self


def load_profiles(directory: Path) -> dict[str, SetupProfile]:
    return {p.stem: SetupProfile.model_validate_json(p.read_text())
            for p in sorted(directory.glob("*.json"))}


def save_profile(directory: Path, profile: SetupProfile) -> None:
    if not re.fullmatch(r"[\w .-]+", profile.chip) or profile.chip.startswith("."):
        raise ValueError("Chip names may only use letters, digits, spaces, '.', '_' and '-'.")
    directory.mkdir(parents=True, exist_ok=True)
    (directory / f"{profile.chip}.json").write_text(profile.model_dump_json(indent=2))


class ChipParameters(BaseModel):
    """Values measured on a chip that later measurements start from (all optional)."""
    model_config = ConfigDict(extra="forbid")

    readout_freq_mhz: float | None = None
    readout_gain: float | None = Field(None, ge=0, le=1)
    qubit_freq_mhz: float | None = None
    qubit_gain: float | None = Field(None, ge=0, le=1)
    pi_gain: float | None = Field(None, ge=0, le=1)
    pi_sigma_us: float | None = Field(None, gt=0)


def load_parameters(directory: Path, chip: str) -> ChipParameters:
    path = directory / "parameters" / f"{chip}.json"
    return ChipParameters.model_validate_json(path.read_text()) if path.exists() else ChipParameters()


def update_parameters(directory: Path, chip: str, changes: ChipParameters) -> ChipParameters:
    """Add or overwrite the values given in `changes`; others stay as they were."""
    merged = load_parameters(directory, chip).model_copy(update=changes.model_dump(exclude_unset=True))
    (directory / "parameters").mkdir(parents=True, exist_ok=True)
    (directory / "parameters" / f"{chip}.json").write_text(merged.model_dump_json(indent=2, exclude_none=True))
    return merged
