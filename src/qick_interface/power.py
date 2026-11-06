"""Absolute power scales of the board's converters, for the Units switch (dB → dBm, a.u. → mV).

All powers are at the board's SMA connectors, 50 Ω, at the IF (after any receive mixer, before any transmit
mixer). Each DAC has a table of its output power at gain 1.0 (const pulse) against frequency; each ADC a table
of its full-scale input power. The data sheets' tables (docs/research/converter-power-scale.md) are built in;
measured ones are added to the library: a DAC's with a signal analyzer (calibrate_dac_with_analyzer), an ADC's
from the loopback (calibrate_adc_from_loopback), or typed into the Board tab. Each chip's setup picks one table
per port (SetupProfile.calibrations), or none: powers then come relative to the converters' full scale (dBFS).
"""
from datetime import date
from pathlib import Path

import numpy as np
from typing import Literal

from pydantic import BaseModel, Field, model_validator

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
DAC_CAL_MHZ = np.arange(50.0, 4900.0 + 1, 50.0)  # first Nyquist zone of the DACs (4915.2 MHz)
DAC_CAL_GAIN = 1.0  # the table holds the output at gain 1: measured there, no scaling assumed
NOTHING_DBM = -40.0  # a DAC at full scale gives about −1 dBm; below this the analyzer sees no tone
DACS = ("DAC_A", "DAC_B")
ADCS = ("ADC_B", "ADC_C", "ADC_D")
DATASHEET = "data sheet"  # the built-in choices a setup can name, besides a measured table's name
UNCALIBRATED = "none"


class Table(BaseModel):
    points: list[tuple[float, float]]  # (MHz, dBm), sorted by frequency
    source: str = DATASHEET  # where it comes from; also its name among the port's tables
    unit: Literal["dBm", "dBFS"] = "dBm"  # dBFS: no calibration, 0 at the converter's full scale

    def at(self, f_mhz):
        f, dbm = np.array(self.points).T
        return np.interp(np.abs(f_mhz), f, dbm)  # flat beyond the ends


class BoardCalibration(BaseModel):
    """Stored in profiles/board/calibration.json; shared by every chip."""
    dac_full_scale_dbm: dict[str, Table] = Field(default_factory=lambda: {
        port: Table(points=DATASHEET_DAC) for port in DACS})
    adc_full_scale_dbm: dict[str, Table] = Field(default_factory=lambda: {
        port: Table(points=DATASHEET_ADC) for port in ADCS})

    def dac_dbm(self, port: str, f_mhz, gain):
        """Output power at the DAC's SMA for a const pulse at this gain."""
        with np.errstate(divide="ignore"):
            return self.dac_full_scale_dbm[port].at(f_mhz) + 20 * np.log10(np.abs(gain))

    def adc_dbm(self, port: str, f_mhz, counts):
        """Input power at the ADC's SMA that reads |I+jQ| = counts."""
        with np.errstate(divide="ignore"):
            return self.adc_full_scale_dbm[port].at(f_mhz) + 20 * np.log10(np.abs(counts) / FULL_SCALE_COUNTS)

    def adc_linear_per_count(self, port: str, f_mhz):
        """Per count of |I+jQ|: peak millivolts at the ADC's SMA, or percent of full scale without a calibration."""
        if self.adc_full_scale_dbm[port].unit == "dBFS":
            return 100.0 / FULL_SCALE_COUNTS
        full_scale_w = 10 ** (self.adc_full_scale_dbm[port].at(f_mhz) / 10) / 1000
        return np.sqrt(2 * LOAD_OHMS * full_scale_w) / FULL_SCALE_COUNTS * 1e3

    def adc_units(self, port: str) -> tuple[str, str]:
        """The units of adc_dbm and adc_linear_per_count for this ADC: (dBm, mV), or (dBFS, % FS) uncalibrated."""
        return ("dBFS", "% FS") if self.adc_full_scale_dbm[port].unit == "dBFS" else ("dBm", "mV")

    def sources(self) -> dict[str, str]:
        """Which table each port uses, for a run's metadata."""
        return {port: t.source for port, t in {**self.dac_full_scale_dbm, **self.adc_full_scale_dbm}.items()}


class CalibrationLibrary(BaseModel):
    """Stored in profiles/board/calibration.json, shared by every chip: each port's measured or typed-in tables,
    oldest first, named by their source. The data sheet's tables and no calibration are built in."""
    dac: dict[str, list[Table]] = Field(default_factory=lambda: {port: [] for port in DACS})
    adc: dict[str, list[Table]] = Field(default_factory=lambda: {port: [] for port in ADCS})

    @model_validator(mode="before")
    @classmethod
    def _from_one_table_per_port(cls, data):
        """The file before 2026-11-06 held one table per port, the data sheet's included."""
        if isinstance(data, dict) and "dac_full_scale_dbm" in data:
            measured = lambda tables: {port: [t] for port, t in tables.items()
                                       if (t.source if isinstance(t, Table) else t.get("source", DATASHEET)) != DATASHEET}
            data = {"dac": measured(data["dac_full_scale_dbm"]), "adc": measured(data.get("adc_full_scale_dbm", {}))}
        return data

    @model_validator(mode="after")
    def _every_port_with_distinct_names(self):
        for ports, kind in ((DACS, self.dac), (ADCS, self.adc)):
            for port in ports:
                kind.setdefault(port, [])
            for port, tables in kind.items():
                names = [t.source for t in tables]
                if len(set(names)) < len(names):
                    raise ValueError(f"Two of {port}'s tables have the same name.")
                if DATASHEET in names or UNCALIBRATED in names:
                    raise ValueError(f"“{DATASHEET}” and “{UNCALIBRATED}” name the built-in choices; "
                                     f"give {port}'s table another name.")
        return self

    def _kind(self, port: str) -> dict[str, list[Table]]:
        if port in self.dac:
            return self.dac
        if port in self.adc:
            return self.adc
        raise KeyError(f"No converter called {port}.")

    def table(self, port: str, choice: str | None = None) -> Table:
        """The table a setup's choice names: None the newest (the data sheet's when none was measured),
        "data sheet", "none" (dBFS), or a table's name."""
        tables = self._kind(port)[port]
        if choice == UNCALIBRATED:
            return Table(points=[(0.0, 0.0)], source="no calibration", unit="dBFS")
        datasheet = Table(points=DATASHEET_DAC if port in self.dac else DATASHEET_ADC)
        if choice == DATASHEET or (choice is None and not tables):
            return datasheet
        if choice is None:
            return tables[-1]
        for t in tables:
            if t.source == choice:
                return t
        raise ValueError(f"{port}'s calibration “{choice}” is no longer on the board; choose another in the "
                         "chip's Setup.")

    def resolve(self, choices: dict[str, str]) -> BoardCalibration:
        """The tables a chip's setup uses (SetupProfile.calibrations; a port it does not name: the newest)."""
        return BoardCalibration(dac_full_scale_dbm={p: self.table(p, choices.get(p)) for p in self.dac},
                                adc_full_scale_dbm={p: self.table(p, choices.get(p)) for p in self.adc})

    def add(self, port: str, table: Table) -> tuple["CalibrationLibrary", str]:
        """A new library with the table appended (renamed "… (2)" if its name is taken), and its name."""
        tables = self._kind(port)[port]
        name, n = table.source, 2
        while name in {t.source for t in tables} | {DATASHEET, UNCALIBRATED}:
            name, n = f"{table.source} ({n})", n + 1
        kind = "dac" if port in self.dac else "adc"
        added = {**getattr(self, kind), port: [*tables, table.model_copy(update={"source": name})]}
        return self.model_copy(update={kind: added}), name


# In a subfolder: every *.json directly in the profiles folder is a chip's setup
def _path(directory: Path) -> Path:
    return directory / "board" / "calibration.json"


def load_board(directory: Path) -> CalibrationLibrary:
    old = directory / "board.json"  # where the first version kept it, among the chips
    if old.exists() and not _path(directory).exists():
        _path(directory).parent.mkdir(parents=True, exist_ok=True)
        old.rename(_path(directory))
    path = _path(directory)
    return CalibrationLibrary.model_validate_json(path.read_text()) if path.exists() else CalibrationLibrary()


def save_board(directory: Path, library: CalibrationLibrary) -> None:
    _path(directory).parent.mkdir(parents=True, exist_ok=True)
    _path(directory).write_text(library.model_dump_json(indent=2))


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


def calibrate_dac_with_analyzer(board, analyzer, calibration: BoardCalibration, dac: str,
                                cable_loss_db: float) -> BoardCalibration:
    """The DAC's output at gain 1, a CW tone every 50 MHz read on a signal analyzer through a cable of
    cable_loss_db. Returns a new calibration with that DAC's table replaced."""
    from .profiles import SetupProfile
    from .tone import OutputTone, tone_program

    profile = SetupProfile(chip="DAC calibration", lo_mhz=None, readout_dac=dac)
    points = []
    analyzer.prepare()
    try:
        for f in DAC_CAL_MHZ:
            board.play(tone_program(board.soccfg, profile, OutputTone(chip=profile.chip, rf_mhz=f, gain=DAC_CAL_GAIN)))
            read = analyzer.peak_dbm(f)
            if read < NOTHING_DBM:
                raise ValueError(f"The analyzer sees almost nothing from {dac} at {f:g} MHz ({read:.1f} dBm); "
                                 "check the cable from that DAC to the analyzer.")
            points.append((float(f), round(read + cable_loss_db, 2)))
    finally:
        board.silence()
        analyzer.release()
    table = Table(points=points, source=f"{analyzer.model}, cable {cable_loss_db:g} dB, {date.today()}")
    return calibration.model_copy(update={"dac_full_scale_dbm": {**calibration.dac_full_scale_dbm, dac: table}})


def drive_hints(measurement, profile, params: dict, calibration: BoardCalibration) -> dict[str, str]:
    """For each gain field the measurement declares in drive_fields, its power at the DAC's SMA, as a hint:
    "≈ −7.0 dBm at DAC_B (data sheet)". Fields whose frequency is not filled in, or not playable, get none."""
    from .frequency import FrequencyError, plan_sweep

    hints = {}
    for field, (freq, line, shape) in measurement.drive_fields.items():
        value = lambda name: params.get(name, measurement.Params.model_fields[name].default)
        shape = shape(value) if callable(shape) else shape  # it may depend on another field
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
        # QICK plays a Gaussian's peak, and a flat_top's flat part, at half the gain
        dbm = calibration.dac_dbm(port, if_mhz, gain * factor) - (6.02 if shape in ("gauss", "flat_top") else 0.0)
        if np.isfinite(dbm):
            peak = " peak" if shape == "gauss" else ""
            source = calibration.dac_full_scale_dbm[port].source
            unit = calibration.dac_full_scale_dbm[port].unit
            hints[field] = f"≈ {float(dbm):.1f} {unit}{peak} at {port} ({source})".replace("-", "−")
    return hints
