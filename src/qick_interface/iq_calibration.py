"""TX I/Q calibration on the signal analyzer, for the I/Q cal tab's Calibrate key.

The mixer's RF output is cabled to the analyzer. A tone at IF f comes out at LO ± f (the setup's sideband);
its image, on the other side of the LO, is what the calibration minimises:

1. The Q delay. With no delay correction, the Q phase that best suppresses the image moves by 360°·f·τ.
   It is found at IFs that double from 50 MHz, each unwrapped against the line through the ones before
   (starting from 90° at 0 Hz, an ideal mixer), which keeps τ unambiguous up to ±10 ns.
2. With that delay, the best Q phase and Q/I gain at each IF of the grid: the setup's I/Q table.

In mW, the image is exactly A − B·cos(φ − φ*) in the Q phase φ, and a parabola in the Q/I gain once the
I DAC's share is put back (outputs() turns I down when Q/I > 1), so a few readings fit each.
"""
import numpy as np

from .profiles import SetupProfile
from .tone import OutputTone, tone_program

DELAY_IFS_MHZ = (50.0, 100.0, 200.0, 400.0, 800.0, 1600.0)
GAIN = 0.5
NOTHING_DBM = -50.0  # the tone comes out near −13 dBm at gain 0.5; below this the analyzer isn't cabled
ROUNDS = ((20.0, 0.16), (6.0, 0.05))  # phase window (°) and gain window (fraction) of each refinement


def calibrate(board, analyzer, profile: SetupProfile, if_start_mhz: float = 50.0, if_stop_mhz: float = 3000.0,
              if_step_mhz: float = 250.0, gain: float = GAIN) -> dict:
    """The Q delay and the I/Q table for this setup's LO and sideband, and the image suppression reached
    at each IF: {"iq_delay_ps", "iq_table": [(IF, phase, gain)], "suppression": [{...}]}."""
    if profile.output_path != "iq":
        raise ValueError("The TX I/Q calibration needs a setup whose Output path is I/Q.")
    if profile.lo_mhz is None:
        raise ValueError("The TX I/Q calibration needs the setup's LO frequency.")
    grid = list(np.arange(if_start_mhz, if_stop_mhz, if_step_mhz)) + [if_stop_mhz]
    sign = 1 if profile.sideband == "upper" else -1
    bench = _Bench(board, analyzer, profile.model_copy(update={"iq_table": [], "iq_delay_ps": 0.0}), sign, gain)
    analyzer.prepare()
    try:
        bench.check_cabled(grid[0])
        delay_ps = _delay(bench, [f for f in DELAY_IFS_MHZ if f <= max(if_stop_mhz, 100.0)])
        bench.profile = bench.profile.model_copy(update={"iq_delay_ps": delay_ps})
        table, suppression = [], []
        phase, ratio = 90.0, 1.0
        for f in grid:
            for window, spread in ROUNDS:
                phase = bench.best_phase(f, phase, ratio, window)
                ratio = bench.best_ratio(f, phase, ratio, spread)
            wanted, image = bench.read(f, phase, ratio)
            table.append((round(float(f), 1), round(phase, 2), round(ratio, 4)))
            suppression.append({"if_mhz": round(float(f), 1), "wanted_dbm": round(wanted, 1),
                                "image_dbm": round(image, 1), "image_below_wanted_db": round(wanted - image, 1)})
    finally:
        board.silence()
        analyzer.release()
    return {"iq_delay_ps": delay_ps, "iq_table": table, "suppression": suppression}


def _delay(bench, ifs) -> float:
    """τ from the best uncorrected Q phase at each IF (ps; Q's DAC ahead of I's)."""
    known = [(0.0, 90.0)]  # an ideal mixer, until two IFs are measured
    measured = []
    for f in ifs:
        best = bench.best_phase(f, 90.0, 1.0, None)
        best = bench.best_phase(f, best, 1.0, 15.0)
        points = measured if len(measured) >= 2 else known + measured
        x, y = np.array(points).T
        predicted = np.polyval(np.polyfit(x, y, 1), f) if len(points) >= 2 else y[0]
        measured.append((f, best + 360.0 * round((predicted - best) / 360.0)))
    x, y = np.array(measured).T
    slope = np.polyfit(x, y, 1)[0]  # ° per MHz; the best phase falls as Q's lead grows (upper sideband)
    return round(float(-bench.sign * slope / 360.0 * 1e6), 1)


class _Bench:
    def __init__(self, board, analyzer, profile, sign, gain):
        self.board, self.analyzer, self.profile, self.sign, self.gain = board, analyzer, profile, sign, gain

    def _play(self, f, phase, ratio):
        p = self.profile.model_copy(update={"iq_phase_deg": phase, "iq_gain_ratio": ratio})
        rf = p.lo_mhz + self.sign * f
        self.board.play(tone_program(self.board.soccfg, p, OutputTone(chip=p.chip, rf_mhz=rf, gain=self.gain)))

    def read(self, f, phase, ratio) -> tuple[float, float]:
        """The wanted tone and its image (dBm)."""
        self._play(f, phase, ratio)
        lo = self.profile.lo_mhz
        return self.analyzer.peak_dbm(lo + self.sign * f), self.analyzer.peak_dbm(lo - self.sign * f)

    def image_mw(self, f, phase, ratio) -> float:
        self._play(f, phase, ratio)
        return 10 ** (self.analyzer.peak_dbm(self.profile.lo_mhz - self.sign * f) / 10)

    def check_cabled(self, f):
        wanted, image = self.read(f, 90.0, 1.0)
        if max(wanted, image) < NOTHING_DBM:
            lo = self.profile.lo_mhz
            raise ValueError(f"The analyzer sees almost nothing at {lo - f:g} or {lo + f:g} MHz "
                             f"({max(wanted, image):.1f} dBm): check the cable from the mixer's RF output to the "
                             "analyzer, and that the LO is on at the setup's frequency.")

    def best_phase(self, f, around, ratio, window) -> float:
        """The Q phase of least image: six phases round the circle (window None), or five within ±window."""
        phases = np.arange(0.0, 360.0, 60.0) if window is None else around + np.linspace(-window, window, 5)
        p = [self.image_mw(f, x, ratio) for x in phases]
        rad = np.radians(phases)
        a = np.linalg.lstsq(np.c_[np.ones(len(rad)), np.cos(rad), np.sin(rad)], p, rcond=None)[0]
        best = float(np.degrees(np.arctan2(-a[2], -a[1])))
        return best + 360.0 * round((around - best) / 360.0)  # the turn nearest the guess

    def best_ratio(self, f, phase, around, spread) -> float:
        ratios = around * (1 + np.linspace(-spread, spread, 5))
        # outputs() plays I at 1/Q/I when Q/I > 1: put that back and the image is a parabola in Q/I
        p = [self.image_mw(f, phase, r) * max(1.0, r) ** 2 for r in ratios]
        c = np.polyfit(ratios, p, 2)
        return float(np.clip(-c[1] / (2 * c[0]), 0.5, 1.5)) if c[0] > 0 else float(around)
