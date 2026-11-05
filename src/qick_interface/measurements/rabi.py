"""Rabi: sweep the qubit pulse amplitude (Gaussian) or length (flat, or flat with Gaussian edges) and fit a
damped cosine. Why these shapes: docs/research/pulse-shapes.md."""
import warnings
from collections.abc import Callable, Iterator
from typing import Literal

import numpy as np
from pydantic import BaseModel, Field
from qick.asm_v2 import AveragerProgramV2, QickSweep1D
from scipy.optimize import OptimizeWarning, curve_fit

from ..frequency import plan_drive, plan_sweep
from ..iq import TonesMixin, control_outputs, inputs, outputs, send_readouts
from ..profiles import SetupProfile
from ..tone import LOOP_MAX
from .base import Update, received_mv, received_s21


def _f(default=..., group=None, unit=None, chip=None, when=None, **kw):
    extra = {k: v for k, v in (("group", group), ("unit", unit), ("from_chip", chip), ("shown_when", when)) if v}
    return Field(default, json_schema_extra=extra, **kw)


class RabiParams(BaseModel):
    sweep: Literal["amplitude", "length"] = _f("amplitude", group="Sweep", title="Sweep")
    start: float = _f(0.0, group="Sweep", ge=0, title="Start", description="gain, or µs for a length sweep")
    stop: float = _f(1.0, group="Sweep", gt=0, title="Stop", description="gain, or µs for a length sweep")
    points: int = _f(101, group="Sweep", ge=3, le=2001, title="Points")
    qubit_freq_mhz: float = _f(group="Qubit", unit="MHz", chip="qubit_freq_mhz", title="Qubit frequency")
    shape: Literal["flat", "gaussian edges"] = _f("flat", group="Qubit", when={"sweep": "length"}, title="Shape",
                                                  description="Gaussian edges: a flat part, swept, between two Gaussian "
                                                              "edges. QICK plays it at half the gain.")
    edge_sigma_us: float = _f(0.005, group="Qubit", unit="µs", gt=0, le=0.5,
                              when={"sweep": "length", "shape": "gaussian edges"}, title="Edge σ",
                              description="Each edge lasts 4σ.")
    qubit_gain: float = _f(0.5, group="Qubit", chip="qubit_gain", ge=0, le=1, when={"sweep": "length"}, title="Qubit gain")
    sigma_us: float = _f(0.02, group="Qubit", unit="µs", chip="pi_sigma_us", gt=0, le=10,
                         when={"sweep": "amplitude"}, title="Gaussian σ")
    readout_freq_mhz: float = _f(group="Readout", unit="MHz", chip="readout_freq_mhz", title="Readout frequency")
    readout_gain: float = _f(0.5, group="Readout", chip="readout_gain", ge=0, le=1, title="Readout gain")
    readout_gap_us: float = _f(0.05, group="Readout", unit="µs", ge=0, le=100, title="Delay before readout",
                               description="From the end of the qubit pulse to the start of the readout pulse.")
    readout_pulse_us: float = _f(2.0, group="Readout", unit="µs", gt=0, le=100, title="Readout pulse length")
    readout_length_us: float = _f(1.5, group="Readout", unit="µs", gt=0, le=100, title="Readout window")
    averages: int = _f(500, group="Average", ge=1, title="Averages per round")
    rounds: int = _f(10, group="Average", ge=1, title="Rounds")
    final_delay_us: float = _f(500.0, group="Average", unit="µs", ge=0, title="Repetition delay",
                              description="Wait between shots so the qubit relaxes: about 5×T1.")
    # the one shot the Output menu's sequence repeats
    scope_gain: float = _f(0.5, group="Output", chip="pi_gain", ge=0, le=1, when={"sweep": "amplitude"},
                           title="Qubit gain", description="The one qubit gain the sequence plays.")
    scope_length_us: float = _f(0.1, group="Output", unit="µs", gt=0, le=100, when={"sweep": "length"},
                                title="Qubit pulse length", description="The one pulse length the sequence plays.")


class _Program(TonesMixin, AveragerProgramV2):
    def _initialize(self, cfg):
        self.declare_outputs(cfg)
        self.declare_inputs(cfg, length=cfg["readout_length"])
        self.add_readout(cfg, "ro", freq=cfg["readout_freq"])
        self.add_loop("sweep", cfg["points"])
        if cfg["sweep"] == "amplitude":
            self.add_gauss_envelope(cfg, "gauss", sigma=cfg["sigma"], length=4 * cfg["sigma"], line="control")
            self.add_tone(cfg, "qubit", freq=cfg["qubit_freq"], gain=cfg["swept"], style="arb", envelope="gauss",
                          line="control")
        elif cfg["shape"] == "gaussian edges":  # the flat part is swept; the ramps are the two halves of 8σ
            sigma = cfg["edge_sigma"]
            self.add_gauss_envelope(cfg, "edges", sigma=sigma, length=8 * sigma, line="control", flat_top=True)
            self.add_tone(cfg, "qubit", freq=cfg["qubit_freq"], gain=cfg["qubit_gain"], length=cfg["swept"],
                          style="flat_top", envelope="edges", line="control")
        else:
            self.add_tone(cfg, "qubit", freq=cfg["qubit_freq"], gain=cfg["qubit_gain"], length=cfg["swept"],
                          line="control")
        self.add_tone(cfg, "readout", freq=cfg["readout_freq"], gain=cfg["readout_gain"],
                      length=cfg["readout_pulse"])

    def _body(self, cfg):
        send_readouts(self, cfg, "ro")
        self.play_tone(cfg, "qubit", t=0)
        if cfg["scope"]:  # PMOD0_0 is high while the qubit pulse plays
            self.trigger(pins=[0], t=0, width=_qubit_pulse_us(cfg))
        self.delay_auto(t=cfg["readout_gap"])  # from the end of the qubit pulse
        self.play_tone(cfg, "readout", t=0)
        self.read(cfg, pins=None if cfg["scope"] else [0], t=cfg["trigger_delay"])



def _qubit_pulse_us(cfg):
    """The whole qubit pulse, edges included (the scope sequence plays one length, not a sweep)."""
    if cfg["sweep"] == "amplitude":
        return 4 * cfg["sigma"]
    return cfg["swept"] + (8 * cfg["edge_sigma"] if cfg["shape"] == "gaussian edges" else 0)


def _check_lengths(soccfg, profile, params, length_us, field):
    """QICK plays no pulse shorter than 3 cycles of the generator's clock (asm_v2: "shorter than the
    min of 3"), nor an envelope longer than its waveform memory; say so in the app's terms before QICK
    does. length_us: the shortest flat pulse asked for (a length sweep's Start, or the Output length),
    named by `field`; a Gaussian lasts 4σ, and so does each Gaussian edge, a segment of its own."""
    gen = control_outputs(soccfg, profile)[0].gen
    shortest_us = soccfg.cycles2us(3, gen_ch=gen)
    cycle_ns = 1e3 / soccfg["gens"][gen]["f_fabric"]
    limit = f"The shortest qubit pulse is {shortest_us * 1e3:.1f} ns (3 cycles of {cycle_ns:.2f} ns)"
    if params.sweep == "length" and length_us < shortest_us:
        raise ValueError(f"{limit}; set {field} to at least {shortest_us:.4f} µs.")
    if params.sweep == "amplitude" and 4 * params.sigma_us < shortest_us:
        raise ValueError(f"{limit}, and the Gaussian lasts 4σ; set σ to at least {shortest_us / 4 * 1e3:.2f} ns.")
    # a shaped pulse is stored in the generator's waveform memory (65536 samples on this firmware)
    g = soccfg["gens"][gen]
    longest_us = g["maxlen"] / (g["samps_per_clk"] * g["f_fabric"])
    if params.sweep == "amplitude" and 4 * params.sigma_us > longest_us:
        raise ValueError(f"The longest qubit envelope is {longest_us:.2f} µs (the DAC's waveform memory), and the "
                         f"Gaussian lasts 4σ; set σ to at most {longest_us / 4:.3f} µs.")
    if params.sweep == "length" and params.shape == "gaussian edges" and 4 * params.edge_sigma_us < shortest_us:
        raise ValueError(f"{limit}, and each edge lasts 4σ; set Edge σ to at least {shortest_us / 4 * 1e3:.2f} ns.")


class Rabi:
    name = "Rabi"
    Params = RabiParams
    x_axis = {"title": "Qubit gain", "unit": ""}
    marker_sets = None
    drive_fields = {"qubit_gain": ("qubit_freq_mhz", "qubit", lambda p: "flat_top" if p("shape") == "gaussian edges" else "flat"), "scope_gain": ("qubit_freq_mhz", "qubit", "gauss"),
                    "readout_gain": ("readout_freq_mhz", "readout", "flat")}
    # each window's first view is the default; Scale → Show picks another (display only, per browser).
    # Signal is what the fit uses; the raw views are for checking it (docs/research/iq-projection.md).
    _signal = {"title": "Signal", "unit": "a.u.", "traces": ["Signal", "Fit"],
               "absolute": {"title": "Signal at the ADC", "unit": "mV", "traces": ["Signal (mV)", "Fit (mV)"]}}
    _raw = [{"title": name, "unit": "a.u.", "traces": [name],
             "absolute": {"title": f"{name} at the ADC", "unit": "mV", "traces": [f"{name} (mV)"]}}
            for name in ("I", "Q", "|S21|")]
    _iq = {"title": "I/Q plane", "unit": "a.u.", "iq": True, "traces": ["I", "Q", "Fit I", "Fit Q"],
           "absolute": {"title": "I/Q plane at the ADC", "unit": "mV", "iq": True,
                        "traces": ["I (mV)", "Q (mV)", "Fit I (mV)", "Fit Q (mV)"]}}
    _phase = {"title": "Phase", "unit": "°", "traces": ["Phase (°)"]}
    plots = [{**_signal, "views": [_signal, *_raw]}, {**_phase, "views": [_phase, _iq]}]
    info_sets = {"π-pulse gain": "pi_gain"}  # fit result -> chip parameter it can be stored as

    @staticmethod
    def x_values(program) -> np.ndarray:
        """Swept gain, or pulse length in µs, at each point, as rounded by QICK."""
        param = "gain" if program.cfg["sweep"] == "amplitude" else "length"
        return program.get_pulse_param("qubit", param, as_array=True)

    @staticmethod
    def _program(soccfg, profile, params, swept, points, reps, scope=False):
        qubit = plan_drive(profile, params.qubit_freq_mhz, params.qubit_freq_mhz)
        readout = plan_sweep(profile, params.readout_freq_mhz, params.readout_freq_mhz)
        return _Program(soccfg, reps=reps, final_delay=params.final_delay_us, cfg={
            "outputs": outputs(soccfg, profile),
            "control": control_outputs(soccfg, profile),
            "inputs": inputs(soccfg, profile),
            "sweep": params.sweep,
            "swept": swept,
            "points": points,
            "qubit_freq": qubit.if_start,
            "qubit_gain": params.qubit_gain,
            "sigma": params.sigma_us,
            "shape": params.shape,
            "edge_sigma": params.edge_sigma_us,
            "readout_freq": readout.if_start,
            "readout_gain": params.readout_gain,
            "readout_gap": params.readout_gap_us,
            "readout_pulse": params.readout_pulse_us,
            "readout_length": params.readout_length_us,
            "trigger_delay": profile.time_of_flight_us,
            "scope": scope,
        })

    @classmethod
    def sequence(cls, soccfg, profile: SetupProfile, params: RabiParams):
        """One shot at the Output menu's gain (or length), repeated until silenced, for an oscilloscope."""
        at = params.scope_gain if params.sweep == "amplitude" else params.scope_length_us
        _check_lengths(soccfg, profile, params, params.scope_length_us, "the Output length")
        return cls._program(soccfg, profile, params, at, points=LOOP_MAX, reps=LOOP_MAX, scope=True)

    @classmethod
    def run(cls, board, profile: SetupProfile, params: RabiParams,
            should_stop: Callable[[], bool] = lambda: False) -> Iterator[Update]:
        _check_lengths(board.soccfg, profile, params, min(params.start, params.stop), "Start")
        program = cls._program(board.soccfg, profile, params, QickSweep1D("sweep", params.start, params.stop),
                               points=params.points, reps=params.averages)
        x = cls.x_values(program)
        if params.sweep == "amplitude":
            x_axis, info_name = {"title": "Qubit gain", "unit": ""}, "π-pulse gain"
        elif params.shape == "gaussian edges":
            edges = 8 * params.edge_sigma_us
            x_axis = {"title": f"Flat length (plus {edges:g} µs of edges)", "unit": "µs"}
            info_name = "π-pulse flat length (µs)"
        else:
            x_axis, info_name = {"title": "Qubit pulse length", "unit": "µs"}, "π-pulse length (µs)"

        for i, iq in enumerate(board.run(program, params.rounds, should_stop), start=1):
            s21 = received_s21(iq, program, "readout", profile)
            signal, centre, axis = _project(s21, x)
            fit, x_pi = _fit_damped_cosine(x, signal)
            fit_iq = centre + fit * axis  # the fit drawn back in the I/Q plane, along the projection axis
            phase = np.degrees(np.angle(s21 * np.exp(-1j * np.angle(np.mean(s21)))))
            mv = lambda v: received_mv(v, program, "readout", profile, board.calibration)
            traces = {"Signal": signal, "Fit": fit, "Phase (°)": phase,
                      "I": s21.real, "Q": s21.imag, "|S21|": np.abs(s21), "Fit I": fit_iq.real, "Fit Q": fit_iq.imag}
            traces |= {f"{name} (mV)": mv(traces[name]) for name in
                       ("Signal", "Fit", "I", "Q", "|S21|", "Fit I", "Fit Q")}
            yield Update(i, params.rounds, x, traces,
                         raw={"s21": s21}, x_axis=x_axis,
                         info={info_name: x_pi} if x_pi is not None else {})


def _project(s21: np.ndarray, x: np.ndarray) -> tuple[np.ndarray, complex, complex]:
    """I/Q points onto the direction they move along (largest variance), centred on their mean: the averaged
    readout moves along the line from the |0⟩ to the |1⟩ response (docs/research/iq-projection.md).
    The eigensolver's sign is arbitrary, so the axis is turned to point away from the zero-drive end, as
    Quantify does: the signal rises from |0⟩. Returns the signal, the centre and the axis (unit complex)."""
    centre = s21.mean()
    z = s21 - centre
    w, v = np.linalg.eigh(np.cov(np.vstack([z.real, z.imag])))
    axis = complex(*v[:, np.argmax(w)])
    signal = z.real * axis.real + z.imag * axis.imag
    if signal[np.argmin(np.abs(x))] > 0:
        signal, axis = -signal, -axis
    return signal, centre, axis


def _damped_cosine(x, amp, freq, phase, offset, decay):
    return amp * np.exp(-x / decay) * np.cos(2 * np.pi * freq * x + phase) + offset


def _fit_damped_cosine(x, y):
    """Best-fit curve and the x of the π pulse (half a Rabi period from zero drive, x = 0).
    The π pulse is None when the fit doesn't explain the data (R² < 0.8) or falls outside the sweep."""
    span = x[-1] - x[0]
    scale = np.std(y) or 1.0
    yn = (y - y.mean()) / scale  # the optimizer behaves better on unit-size data
    spectrum = np.abs(np.fft.rfft(yn, n=8 * len(y)))
    freqs = np.fft.rfftfreq(8 * len(y), d=span / (len(y) - 1))
    f0 = freqs[1 + np.argmax(spectrum[1:])]
    best = None
    for phase0 in (0.0, np.pi):
        try:
            # offset starts slightly off 0: the optimizer's step is relative and never leaves an exact 0
            # no decay in the data leaves the decay time undetermined; trial decays may overflow exp
            with warnings.catch_warnings(), np.errstate(over="ignore"):
                warnings.simplefilter("ignore", OptimizeWarning)
                p, _ = curve_fit(_damped_cosine, x, yn, maxfev=5000, p0=[1.4, f0, phase0, 0.01, 3 * span])
        except (RuntimeError, ValueError):
            continue
        err = np.sum((_damped_cosine(x, *p) - yn) ** 2)
        if best is None or err < best[0]:
            best = (err, p)
    if best is None:
        return np.full_like(y, np.nan), None
    amp, freq, phase, offset, decay = best[1]
    curve = _damped_cosine(x, *best[1]) * scale + y.mean()
    if amp < 0:
        amp, phase = -amp, phase + np.pi
    freq, phase = abs(freq), np.copysign(1, freq) * phase
    k = np.round(phase / np.pi)  # zero drive (x = 0) sits on an extremum of the cosine
    x_pi = ((k + 1) * np.pi - phase) / (2 * np.pi * freq)
    r_squared = 1 - best[0] / np.sum(yn ** 2)
    if r_squared < 0.8 or not x[0] <= x_pi <= x[-1]:
        return curve, None  # no clear oscillation: don't claim a π pulse
    return curve, float(x_pi)
