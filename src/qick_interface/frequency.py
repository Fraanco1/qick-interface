"""RF <-> IF planning for a setup profile. Pure functions, no hardware."""
from dataclasses import dataclass

from .profiles import SetupProfile

# First Nyquist zones of the board firmware: readouts sample at 4423.68 Msps, generators at 9830.4 Msps.
MAX_IF_MHZ = 4423.68 / 2
MAX_DRIVE_IF_MHZ = 9830.4 / 2


class FrequencyError(ValueError):
    """A requested frequency can't be reached with this setup profile."""


@dataclass(frozen=True)
class SweepPlan:
    if_start: float
    if_stop: float
    image_start: float | None
    image_stop: float | None


def plan_sweep(profile: SetupProfile, rf_start: float, rf_stop: float, drive_only: bool = False) -> SweepPlan:
    """IF range for an RF range. Readout tones must fit the ADC; tones that are only
    sent (drive_only, e.g. a qubit tone) only need to fit the DAC."""
    lo = profile.lo_mhz
    sign = 1 if profile.sideband == "upper" else -1
    if lo is None:
        if_start, if_stop = rf_start, rf_stop
        if min(if_start, if_stop) <= 0:
            raise FrequencyError(f"Without an LO, RF must be above 0 MHz; requested {rf_start:g}–{rf_stop:g} MHz.")
    else:
        if_start, if_stop = sign * (rf_start - lo), sign * (rf_stop - lo)
        if min(if_start, if_stop) <= 0:
            side = "above" if sign > 0 else "below"
            raise FrequencyError(
                f"With the {profile.sideband} sideband, RF must be {side} the LO "
                f"({lo:g} MHz); requested {rf_start:g}–{rf_stop:g} MHz."
            )

    limit, what = (MAX_DRIVE_IF_MHZ, "output") if drive_only else (MAX_IF_MHZ, "readout")
    if max(if_start, if_stop) > limit:
        raise FrequencyError(
            f"IF up to {max(if_start, if_stop):g} MHz exceeds the {what} limit of "
            f"{limit:.2f} MHz; move the LO closer to the RF range."
        )

    if lo is None:
        return SweepPlan(if_start, if_stop, None, None)
    return SweepPlan(if_start, if_stop, lo - sign * if_start, lo - sign * if_stop)


def plan_drive(profile: SetupProfile, rf_start: float, rf_stop: float) -> SweepPlan:
    """IF range for a qubit tone: straight out of its DAC on a control line (RF = DAC frequency),
    otherwise through the readout line's mixer."""
    return plan_sweep(_drive_line(profile), rf_start, rf_stop, drive_only=True)


def drive_rf_from_if(profile: SetupProfile, if_mhz):
    """RF of a qubit tone at the chip, for a given DAC frequency."""
    return rf_from_if(_drive_line(profile), if_mhz)


def _drive_line(profile: SetupProfile) -> SetupProfile:
    return profile.model_copy(update={"lo_mhz": None}) if profile.control_dac else profile


def rf_from_if(profile: SetupProfile, if_mhz):
    """RF frequency seen by the chip for a given IF (works on arrays)."""
    if profile.lo_mhz is None:
        return if_mhz
    sign = 1 if profile.sideband == "upper" else -1
    return profile.lo_mhz + sign * if_mhz
