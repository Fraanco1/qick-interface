"""Absolute power scales of the board's converters, for the Units switch (dB → dBm, a.u. → mV).

All powers are at the board's SMA connectors, 50 Ω, at the IF (after any receive mixer, before any transmit
mixer). Each DAC has a table of its output power at gain 1.0 (const pulse) against frequency; each ADC a table
of its full-scale input power. The tables start from the data sheets (docs/research/converter-power-scale.md)
and are replaced by measurements: the ADC from the loopback (calibrate_adc_from_loopback), both from a
signal analyzer later (typed into the Board tab).
"""
from datetime import date
from pathlib import Path

import numpy as np
from pydantic import BaseModel, Field

FULL_SCALE_COUNTS = 4225.0  # |I+jQ| per sample for a full-scale ADC tone: 32768 × ¼ (mixing) × 0.516 (FIR)
LOAD_OHMS = 50.0

# Data sheet values (converter-power-scale.md §1.4 and §2), MHz -> dBm at the SMA
DATASHEET_DAC = [(100, -1.1), (550, -1.0), (1000, -0.7), (2000, -0.6), (3000, -1.2), (4000, -2.4), (4500, -3.2)]
DATASHEET_ADC = [(100, 3.0), (550, 3.0), (1000, 2.5), (2000, 2.0), (2200, 2.0)]
LOOPBACK_MHZ = (100.0, 2100.0)  # first Nyquist zone, clear of the readout filter's edge near 2211.84 MHz
LOOPBACK_POINTS = 401  # 5 MHz apart
# The loopback cable's own ripple (a standing wave between the DAC's and the ADC's imperfect 50 Ω ports) has a
# period of c/(2·length·v): 100 MHz for the bench's ~1 m cable, ±0.7 dB. It belongs to the cable, not the ADC,
# so the table is a running mean over one period, sampled once per period.
RIPPLE_MHZ = 100.0
LOOPBACK_GAIN = 0.5


class Table(BaseModel):
    points: list[tuple[float, float]]  # (MHz, dBm), sorted by frequency
    source: str = "data sheet"

    def at(self, f_mhz):
        f, dbm = np.array(self.points).T
        return np.interp(np.abs(f_mhz), f, dbm)  # flat beyond the ends


class BoardCalibration(BaseModel):
    """Stored in profiles/board.json; shared by every chip."""
    dac_full_scale_dbm: dict[str, Table] = Field(default_factory=lambda: {
        port: Table(points=DATASHEET_DAC) for port in ("DAC_A", "DAC_B")})
    adc_full_scale_dbm: dict[str, Table] = Field(default_factory=lambda: {
        port: Table(points=DATASHEET_ADC) for port in ("ADC_B", "ADC_C", "ADC_D")})

    def dac_dbm(self, port: str, f_mhz, gain):
        """Output power at the DAC's SMA for a const pulse at this gain."""
        with np.errstate(divide="ignore"):
            return self.dac_full_scale_dbm[port].at(f_mhz) + 20 * np.log10(np.abs(gain))

    def adc_dbm(self, port: str, f_mhz, counts):
        """Input power at the ADC's SMA that reads |I+jQ| = counts."""
        with np.errstate(divide="ignore"):
            return self.adc_full_scale_dbm[port].at(f_mhz) + 20 * np.log10(np.abs(counts) / FULL_SCALE_COUNTS)

    def adc_volts_per_count(self, port: str, f_mhz):
        """Peak volts at the ADC's SMA per count of |I+jQ|."""
        full_scale_w = 10 ** (self.adc_full_scale_dbm[port].at(f_mhz) / 10) / 1000
        return np.sqrt(2 * LOAD_OHMS * full_scale_w) / FULL_SCALE_COUNTS


def load_board(directory: Path) -> BoardCalibration:
    path = directory / "board.json"
    return BoardCalibration.model_validate_json(path.read_text()) if path.exists() else BoardCalibration()


def save_board(directory: Path, calibration: BoardCalibration) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "board.json").write_text(calibration.model_dump_json(indent=2))


def calibrate_adc_from_loopback(board, calibration: BoardCalibration, dac: str, adc: str) -> BoardCalibration:
    """The ADC's full scale from a short cable dac → adc, trusting the DAC's table (cable loss neglected), as
    a smooth table every RIPPLE_MHZ. Returns a new calibration with that ADC's table replaced."""
    from .measurements.resonator_sweep import ResonatorSweep, ResonatorSweepParams
    from .profiles import SetupProfile

    profile = SetupProfile(chip="loopback", lo_mhz=None, readout_dac=dac, readout_adc=adc)
    params = ResonatorSweepParams(rf_start_mhz=LOOPBACK_MHZ[0], rf_stop_mhz=LOOPBACK_MHZ[1],
                                  points=LOOPBACK_POINTS, gain=LOOPBACK_GAIN, rounds=1)
    program, if_mhz, _ = ResonatorSweep.program(board, profile, params)
    counts = np.abs(next(iter(board.run(program, 1)))[0])
    if np.min(counts) < 0.01 * FULL_SCALE_COUNTS:
        raise ValueError(f"Almost nothing reaches {adc} from {dac}; check the loopback cable.")
    full_scale = calibration.dac_dbm(dac, if_mhz, LOOPBACK_GAIN) - 20 * np.log10(counts / FULL_SCALE_COUNTS)
    n = int(round(RIPPLE_MHZ / abs(if_mhz[1] - if_mhz[0])))  # samples per ripple period
    mean = np.convolve(full_scale, np.ones(n) / n, mode="valid")
    centers = (if_mhz[: len(mean)] + if_mhz[n - 1:]) / 2
    table = Table(points=[(round(float(f), 1), round(float(p), 2)) for f, p in zip(centers[::n], mean[::n])],
                  source=f"loopback from {dac} ({calibration.dac_full_scale_dbm[dac].source}), {date.today()}")
    return calibration.model_copy(update={"adc_full_scale_dbm": {**calibration.adc_full_scale_dbm, adc: table}})


def drive_hints(measurement, profile, params: dict, calibration: BoardCalibration) -> dict[str, str]:
    """For each gain field the measurement declares in drive_fields, its power at the DAC's SMA, as a hint:
    "≈ −7.0 dBm at DAC_B (data sheet)". Fields whose frequency is not filled in, or not playable, get none."""
    from .frequency import FrequencyError, plan_sweep

    hints = {}
    for field, (freq, line, shape) in measurement.drive_fields.items():
        value = lambda name: params.get(name, measurement.Params.model_fields[name].default)
        try:
            gain = float(value(field))
            freqs = [float(value(f)) for f in (freq if isinstance(freq, tuple) else (freq,))]
        except (TypeError, ValueError):
            continue
        rf = sum(freqs) / len(freqs)  # a sweep: its center
        if line == "qubit" and profile.control_dac:
            port, if_mhz, factor = profile.control_dac, rf, 1.0  # its own DAC, no mixer
        else:
            iq = profile.output_path == "iq"
            port = profile.i_dac if iq else profile.readout_dac
            factor = 1 / max(1.0, profile.iq_gain_ratio) if iq else 1.0  # the I DAC's share on the I/Q path
            try:
                if_mhz = plan_sweep(profile, rf, rf, drive_only=line == "qubit").if_start
            except FrequencyError:
                continue
        dbm = calibration.dac_dbm(port, if_mhz, gain * factor) - (6.02 if shape == "gauss" else 0.0)
        if np.isfinite(dbm):
            peak = " peak" if shape == "gauss" else ""
            source = calibration.dac_full_scale_dbm[port].source
            hints[field] = f"≈ {float(dbm):.1f} dBm{peak} at {port} ({source})".replace("-", "−")
    return hints
