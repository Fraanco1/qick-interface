"""Oscilloscope: the voltage at the ADC inputs against time, like a two-channel scope.

Each record is one shot's raw ADC samples, at the ADC's full rate (4.42 GS/s), not downconverted: the
carrier itself shows. The board's multi-rate buffer records 8192 samples (1.85 µs) from the trigger, from
one readout at a time; the readout passes its input through unchanged (outsel="input"). Channel 2 is
recorded on a second, identical shot, so both channels share the time axis. The shot is the readout pulse,
optionally after a qubit pulse (flat as in Two-tone; Gaussian or Gaussian edges as in Rabi). Each redraw is
one new shot per channel (no averaging), until Stop.
"""
import time
from collections.abc import Callable, Iterator
from types import SimpleNamespace
from typing import Literal

import numpy as np
from pydantic import BaseModel, Field
from qick.asm_v2 import AveragerProgramV2

from ..board import readout_channel
from ..frequency import plan_drive, plan_sweep
from ..iq import TonesMixin, control_outputs, outputs
from ..power import FULL_SCALE_COUNTS
from ..profiles import SetupProfile
from .base import Update
from .rabi import _check_lengths

QUBIT = ["flat", "gaussian", "gaussian edges"]
RAW_FULL_SCALE = 32768  # raw counts of a full-scale tone; FULL_SCALE_COUNTS after the readout's downconversion


def _f(default=..., group=None, unit=None, chip=None, when=None, **kw):
    extra = {k: v for k, v in (("group", group), ("unit", unit), ("from_chip", chip), ("shown_when", when)) if v}
    return Field(default, json_schema_extra=extra, **kw)


class OscilloscopeParams(BaseModel):
    channel_1: Literal["readout input", "ADC_B", "ADC_C", "ADC_D"] = _f(
        "readout input", group="Channels", title="Channel 1",
        description="Readout input: the setup's (the I input on an I/Q return path).")
    channel_2: Literal["off", "ADC_B", "ADC_C", "ADC_D"] = _f(
        "off", group="Channels", title="Channel 2", description="Recorded on the next, identical shot.")
    record_start_us: float = _f(0.0, group="Channels", unit="µs", ge=0, le=1000, title="Record start",
                                description="From the start of the shot; each record lasts 1.85 µs.")
    readout_freq_mhz: float = _f(group="Readout", unit="MHz", chip="readout_freq_mhz", title="Readout frequency")
    readout_gain: float = _f(0.5, group="Readout", chip="readout_gain", ge=0, le=1, title="Readout gain")
    readout_pulse_us: float = _f(1.0, group="Readout", unit="µs", gt=0, le=100, title="Readout pulse length")
    qubit_pulse: Literal["none", "flat", "gaussian", "gaussian edges"] = _f(
        "none", group="Qubit", title="Qubit pulse",
        description="Before the readout pulse: flat as in Two-tone, Gaussian or Gaussian edges as in Rabi.")
    qubit_freq_mhz: float | None = _f(None, group="Qubit", unit="MHz", chip="qubit_freq_mhz", when={"qubit_pulse": QUBIT},
                                      title="Qubit frequency")
    qubit_gain: float = _f(0.5, group="Qubit", chip="qubit_gain", ge=0, le=1, when={"qubit_pulse": QUBIT},
                           title="Qubit gain")
    qubit_length_us: float = _f(0.1, group="Qubit", unit="µs", gt=0, le=100,
                                when={"qubit_pulse": ["flat", "gaussian edges"]}, title="Qubit pulse length",
                                description="With Gaussian edges, the flat part's.")
    sigma_us: float = _f(0.02, group="Qubit", unit="µs", chip="pi_sigma_us", gt=0, le=10,
                         when={"qubit_pulse": "gaussian"}, title="Gaussian σ")
    edge_sigma_us: float = _f(0.005, group="Qubit", unit="µs", gt=0, le=0.5, when={"qubit_pulse": "gaussian edges"},
                              title="Edge σ", description="Each edge lasts 4σ.")
    readout_gap_us: float = _f(0.05, group="Qubit", unit="µs", ge=0, le=100, when={"qubit_pulse": QUBIT},
                               title="Delay before readout",
                               description="From the end of the qubit pulse to the start of the readout pulse.")


class _Program(TonesMixin, AveragerProgramV2):
    def _initialize(self, cfg):
        self.declare_outputs(cfg)
        ro = cfg["inputs"][0]
        self.declare_readout(ch=ro, length=0.1)  # the decimated buffer is triggered too; nothing reads it
        self.add_readoutconfig(ch=ro, name="raw", **cfg["readout_config"])
        self.add_tone(cfg, "readout", freq=cfg["readout_freq"], gain=cfg["readout_gain"], length=cfg["readout_pulse"])
        shape = cfg["qubit_pulse"]
        if shape == "flat":
            self.add_tone(cfg, "qubit", freq=cfg["qubit_freq"], gain=cfg["qubit_gain"], length=cfg["qubit_length"],
                          line="control")
        elif shape == "gaussian":
            self.add_gauss_envelope(cfg, "gauss", sigma=cfg["sigma"], length=4 * cfg["sigma"], line="control")
            self.add_tone(cfg, "qubit", freq=cfg["qubit_freq"], gain=cfg["qubit_gain"], style="arb", envelope="gauss",
                          line="control")
        elif shape == "gaussian edges":
            sigma = cfg["edge_sigma"]
            self.add_gauss_envelope(cfg, "edges", sigma=sigma, length=8 * sigma, line="control", flat_top=True)
            self.add_tone(cfg, "qubit", freq=cfg["qubit_freq"], gain=cfg["qubit_gain"], length=cfg["qubit_length"],
                          style="flat_top", envelope="edges", line="control")

    def _body(self, cfg):
        self.send_readoutconfig(ch=cfg["inputs"][0], name="raw", t=0)
        # the record starts here; PMOD0_0 marks it for an external scope
        self.trigger(ros=cfg["inputs"], pins=[0], mr=True, t=cfg["record_start"])
        if cfg["qubit_pulse"] != "none":
            self.play_tone(cfg, "qubit", t=0)
            self.delay_auto(t=cfg["readout_gap"], ros=False)  # after the qubit pulse, not after the record
        self.play_tone(cfg, "readout", t=0)


class Oscilloscope:
    name = "Oscilloscope"
    run_key = "Run"  # it redraws until Stop
    Params = OscilloscopeParams
    x_axis = {"title": "Time", "unit": "µs"}
    drive_fields = {
        "readout_gain": ("readout_freq_mhz", "readout", "flat"),
        "qubit_gain": ("qubit_freq_mhz", "qubit",
                       lambda p: {"gaussian": "gauss", "gaussian edges": "flat_top"}.get(p("qubit_pulse"), "flat")),
    }
    plots = [{"title": f"Channel {k}", "unit": "counts", "traces": [f"Channel {k}"],
              "absolute": {"title": f"Channel {k}", "unit": "mV", "traces": [f"Channel {k} (mV)"]}} for k in (1, 2)]
    marker_sets = None
    info_sets = {}
    MIN_REDRAW_S = 0.2  # each update sends whole traces to every browser: at most 5 a second

    @staticmethod
    def program(soccfg, profile: SetupProfile, params: OscilloscopeParams, adc: str):
        """One shot, recording the raw samples of the ADC port named adc."""
        qubit = None
        if params.qubit_pulse != "none":
            if params.qubit_freq_mhz is None:
                raise ValueError("Enter the Qubit frequency, or set Qubit pulse to none.")
            _check_lengths(soccfg, profile, SimpleNamespace(
                sweep="amplitude" if params.qubit_pulse == "gaussian" else "length",
                shape="gaussian edges" if params.qubit_pulse == "gaussian edges" else "flat",
                sigma_us=params.sigma_us, edge_sigma_us=params.edge_sigma_us), params.qubit_length_us,
                "the Qubit pulse length")
            qubit = plan_drive(profile, params.qubit_freq_mhz, params.qubit_freq_mhz).if_start
        readout = plan_sweep(profile, params.readout_freq_mhz, params.readout_freq_mhz).if_start
        return _Program(soccfg, reps=1, final_delay=1.0, cfg={
            "outputs": outputs(soccfg, profile), "control": control_outputs(soccfg, profile),
            "inputs": [readout_channel(soccfg, adc)],
            "readout_config": {"freq": 0, "outsel": "input"},  # the ADC's samples as they are
            "record_start": params.record_start_us, "readout_rf": params.readout_freq_mhz,
            "readout_freq": readout, "readout_gain": params.readout_gain, "readout_pulse": params.readout_pulse_us,
            "qubit_pulse": params.qubit_pulse, "qubit_freq": qubit, "qubit_gain": params.qubit_gain,
            "qubit_length": params.qubit_length_us, "sigma": params.sigma_us, "edge_sigma": params.edge_sigma_us,
            "readout_gap": params.readout_gap_us})

    @classmethod
    def run(cls, board, profile: SetupProfile, params: OscilloscopeParams,
            should_stop: Callable[[], bool] = lambda: False) -> Iterator[Update]:
        setup_input = profile.i_adc if profile.return_path == "iq" else profile.readout_adc
        adcs = [setup_input if params.channel_1 == "readout input" else params.channel_1]
        if params.channel_2 != "off":
            adcs.append(params.channel_2)
        programs = [cls.program(board.soccfg, profile, params, adc) for adc in adcs]
        fs = board.soccfg["readouts"][programs[0].cfg["inputs"][0]]["fs"]
        # counts → mV at the ADC's SMA, from its calibration at the readout frequency
        mv = [board.calibration.adc_volts_per_count(adc, params.readout_freq_mhz) * FULL_SCALE_COUNTS
              / RAW_FULL_SCALE * 1e3 for adc in adcs]
        i, last = 0, -cls.MIN_REDRAW_S
        while not should_stop():
            time.sleep(max(0.0, last + cls.MIN_REDRAW_S - time.monotonic()))
            last = time.monotonic()
            i += 1
            records = [board.capture_raw(p, p.cfg["inputs"][0]) for p in programs]
            t = params.record_start_us + np.arange(records[0].size) / fs
            traces = {}
            for k in (1, 2):
                v = records[k - 1] if k <= len(records) else np.full(t.size, np.nan)  # off: an empty window
                traces[f"Channel {k}"] = v
                traces[f"Channel {k} (mV)"] = v * mv[k - 1] if k <= len(records) else v
            yield Update(i, None, t, traces)
