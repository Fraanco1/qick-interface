"""RF <-> IF planning for a setup profile. Pure functions, no hardware."""
from dataclasses import dataclass

from .profiles import SetupProfile

# Readouts sample at 4423.68 Msps (board firmware); we only use the first Nyquist zone.
MAX_IF_MHZ = 4423.68 / 2


class FrequencyError(ValueError):
    """A requested frequency can't be reached with this setup profile."""


@dataclass(frozen=True)
class SweepPlan:
    if_start: float
    if_stop: float
    image_start: float | None
    image_stop: float | None


def plan_sweep(profile: SetupProfile, rf_start: float, rf_stop: float) -> SweepPlan:
    lo = profile.lo_mhz
    sign = 1 if profile.sideband == "upper" else -1
    if lo is None:
        if_start, if_stop = rf_start, rf_stop
    else:
        if_start, if_stop = sign * (rf_start - lo), sign * (rf_stop - lo)
        if min(if_start, if_stop) <= 0:
            side = "above" if sign > 0 else "below"
            raise FrequencyError(
                f"With the {profile.sideband} sideband, RF must be {side} the LO "
                f"({lo:g} MHz); requested {rf_start:g}–{rf_stop:g} MHz."
            )

    if max(if_start, if_stop) > MAX_IF_MHZ:
        raise FrequencyError(
            f"IF up to {max(if_start, if_stop):g} MHz exceeds the readout limit of "
            f"{MAX_IF_MHZ:.2f} MHz; move the LO closer to the RF range."
        )

    if lo is None:
        return SweepPlan(if_start, if_stop, None, None)
    return SweepPlan(if_start, if_stop, lo - sign * if_start, lo - sign * if_stop)


def rf_from_if(profile: SetupProfile, if_mhz):
    """RF frequency seen by the chip for a given IF (works on arrays)."""
    if profile.lo_mhz is None:
        return if_mhz
    sign = 1 if profile.sideband == "upper" else -1
    return profile.lo_mhz + sign * if_mhz
