"""FastAPI app: REST + WebSocket + the static page. No measurement logic here."""
from pathlib import Path

import asyncio
from urllib.parse import unquote

import Pyro4
from fastapi import FastAPI, Header, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, ValidationError

from .tone import OutputTone, tone_program
from .iq_delay import measure as measure_iq_delay
from .power import (BoardCalibration, calibrate_adc_from_loopback, calibrate_dac_with_analyzer, drive_hints,
                    load_board, save_board)
from .scpi import ScpiError
from .time_of_flight import measure as measure_time_of_flight
from .frequency import FrequencyError
from .lo import LoError
from .measurements.cw_time import CwTime
from .measurements.resonator_sweep import ResonatorSweep
from .measurements.rabi import Rabi
from .measurements.rx_iq_cal import RxIqCal
from .measurements.oscilloscope import Oscilloscope
from .measurements.two_tone import TwoTone
from .profiles import (ChipParameters, SetupProfile, delete_profile, load_parameters, load_profiles, save_profile,
                       update_parameters)
from .session import Busy, NotController, Session

STATIC = Path(__file__).parent / "static"
MEASUREMENTS = {"resonator_sweep": ResonatorSweep, "cw_time": CwTime, "two_tone": TwoTone, "rabi": Rabi,
                "rx_iq_cal": RxIqCal, "oscilloscope": Oscilloscope}


class RunRequest(BaseModel):
    measurement: str
    chip: str
    params: dict


def create_app(board, data_dir: Path, profiles_dir: Path, lo=None, scope=None, analyzer=None) -> FastAPI:
    app = FastAPI(title="QICK interface")
    session = Session(board, MEASUREMENTS, data_dir, lo)
    app.state.session = session

    @app.get("/api/measurements")
    def measurements():
        return {key: {"name": m.name, "params": m.Params.model_json_schema(), "x_axis": m.x_axis,
                      "plots": m.plots, "marker_sets": m.marker_sets, "info_sets": m.info_sets,
                      "setup_sets": getattr(m, "setup_sets", {}), "setup_label": getattr(m, "setup_label", ""),
                      "sequence": hasattr(m, "sequence"), "run_key": getattr(m, "run_key", "Run sweep"),
                      "setup_requires": getattr(m, "setup_requires", {}),
                      "x_scale": getattr(m, "x_scale", False)}
                for key, m in MEASUREMENTS.items()}

    @app.get("/api/profiles")
    def profiles():
        return load_profiles(profiles_dir)

    @app.put("/api/profiles/{chip}")
    def put_profile(chip: str, profile: SetupProfile, x_client_id: str = Header()):
        if x_client_id != session.controller:
            raise HTTPException(403, "Only the controller can change a setup. Take control first.")
        if chip != profile.chip:
            raise HTTPException(400, "The chip name in the URL and in the profile differ.")
        try:
            save_profile(profiles_dir, profile)
        except ValueError as e:
            raise HTTPException(400, str(e))
        return profile

    @app.delete("/api/profiles/{chip}")
    def remove_profile(chip: str, x_client_id: str = Header()):
        if x_client_id != session.controller:
            raise HTTPException(403, "Only the controller can delete a chip. Take control first.")
        if chip not in load_profiles(profiles_dir):  # also keeps the name to files of saved chips
            raise HTTPException(404, f"No setup profile for chip {chip!r}.")
        delete_profile(profiles_dir, chip)
        return {"deleted": chip}

    @app.get("/api/parameters/{chip}")
    def parameters(chip: str):
        if chip not in load_profiles(profiles_dir):
            raise HTTPException(404, f"No setup profile for chip {chip!r}.")
        return load_parameters(profiles_dir, chip).model_dump(exclude_none=True)

    @app.patch("/api/parameters/{chip}")
    def patch_parameters(chip: str, changes: ChipParameters, x_client_id: str = Header()):
        if x_client_id != session.controller:
            raise HTTPException(403, "Only the controller can change chip parameters. Take control first.")
        if chip not in load_profiles(profiles_dir):
            raise HTTPException(404, f"No setup profile for chip {chip!r}.")
        merged = update_parameters(profiles_dir, chip, changes).model_dump(exclude_none=True)
        session.broadcast({"type": "parameters", "chip": chip, "parameters": merged})
        return merged

    @app.post("/api/control")
    def take_control(x_client_id: str = Header(), x_client_name: str | None = Header(None)):
        session.take_control(x_client_id, unquote(x_client_name) if x_client_name else None)
        return session.state()

    @app.post("/api/runs")
    def start_run(run: RunRequest, x_client_id: str = Header()):
        profile = load_profiles(profiles_dir).get(run.chip)
        if profile is None:
            raise HTTPException(404, f"No setup profile for chip {run.chip!r}.")
        if run.measurement not in MEASUREMENTS:
            raise HTTPException(404, f"Unknown measurement {run.measurement!r}.")
        try:
            session.start(x_client_id, run.measurement, profile, run.params)
        except NotController as e:
            raise HTTPException(403, str(e))
        except Busy as e:
            raise HTTPException(409, str(e))
        except ValidationError as e:
            raise HTTPException(422, [{"field": ".".join(map(str, err["loc"])), "message": err["msg"]}
                                      for err in e.errors()])
        except LoError as e:
            raise HTTPException(422, str(e))
        return session.state()

    @app.post("/api/tone")
    def tone_on(tone: OutputTone, x_client_id: str = Header()):
        profile = load_profiles(profiles_dir).get(tone.chip)
        if profile is None:
            raise HTTPException(404, f"No setup profile for chip {tone.chip!r}.")
        try:
            session.play_tone(x_client_id, tone_program(board.soccfg, profile, tone), tone.model_dump(), profile)
        except NotController as e:
            raise HTTPException(403, str(e))
        except Busy as e:
            raise HTTPException(409, str(e))
        except (FrequencyError, LoError) as e:
            raise HTTPException(422, str(e))
        return session.state()

    @app.post("/api/sequence")
    def sequence_on(run: RunRequest, x_client_id: str = Header()):
        """A pulsed measurement's shot at one point (its Output menu), repeated until Off, for a scope."""
        profile = load_profiles(profiles_dir).get(run.chip)
        if profile is None:
            raise HTTPException(404, f"No setup profile for chip {run.chip!r}.")
        m = MEASUREMENTS.get(run.measurement)
        if not hasattr(m, "sequence"):
            raise HTTPException(404, f"{run.measurement!r} has no sequence to play.")
        try:
            params = m.Params.model_validate(run.params, context={"sequence": True})
            program = m.sequence(board.soccfg, profile, params)
            session.play_tone(x_client_id, program, {"mode": "sequence", "measurement": m.name}, profile)
        except NotController as e:
            raise HTTPException(403, str(e))
        except Busy as e:
            raise HTTPException(409, str(e))
        except ValidationError as e:
            raise HTTPException(422, [{"field": ".".join(map(str, err["loc"])), "message": err["msg"]}
                                      for err in e.errors()])
        except (ValueError, FrequencyError, LoError) as e:
            raise HTTPException(422, str(e))
        return session.state()

    @app.post("/api/time-of-flight")
    def time_of_flight(profile: SetupProfile, x_client_id: str = Header()):
        """Measure it with the setup as edited (not yet saved); the page fills the field."""
        readout = load_parameters(profiles_dir, profile.chip).readout_freq_mhz  # None for a new chip
        try:
            us = session.measure(x_client_id, lambda b: measure_time_of_flight(b, profile, readout), profile)
        except NotController as e:
            raise HTTPException(403, str(e))
        except Busy as e:
            raise HTTPException(409, str(e))
        except (ValueError, FrequencyError, LoError) as e:
            raise HTTPException(422, str(e))
        return {"time_of_flight_us": us}

    board.calibration = load_board(profiles_dir)

    @app.get("/api/board")
    def board_calibration():
        return board.calibration.model_dump()

    @app.put("/api/board")
    def put_board_calibration(calibration: BoardCalibration, x_client_id: str = Header()):
        if x_client_id != session.controller:
            raise HTTPException(403, "Only the controller can change the board calibration. Take control first.")
        save_board(profiles_dir, calibration)
        board.calibration = calibration
        return calibration.model_dump()

    class LoopbackRequest(BaseModel):
        dac: str = "DAC_B"
        adc: str = "ADC_D"

    @app.post("/api/board/adc-from-loopback")
    def adc_from_loopback(req: LoopbackRequest, x_client_id: str = Header()):
        """The ADC's full scale from a cable req.dac → req.adc, trusting the DAC's table; kept in profiles/board/calibration.json."""
        try:
            new = session.measure(x_client_id, lambda b: calibrate_adc_from_loopback(b, b.calibration, req.dac, req.adc),
                                  None)
        except NotController as e:
            raise HTTPException(403, str(e))
        except Busy as e:
            raise HTTPException(409, str(e))
        except (ValueError, KeyError) as e:
            raise HTTPException(422, str(e))
        save_board(profiles_dir, new)
        board.calibration = new
        return new.model_dump()

    @app.get("/api/instruments")
    def instruments():
        """The instruments the app controls: the signal analyzer's model, or None without --analyzer."""
        try:
            model = analyzer.model if analyzer is not None else None
        except ScpiError:
            model = None
        return {"analyzer": model, "lo": lo is not None}

    class AnalyzerRequest(BaseModel):
        dac: str = "DAC_A"
        cable_loss_db: float = Field(0.0, ge=0, le=20)

    @app.post("/api/board/dac-from-analyzer")
    def dac_from_analyzer(req: AnalyzerRequest, x_client_id: str = Header()):
        """The DAC's output at gain 1 measured on the signal analyzer; kept in profiles/board/calibration.json."""
        if analyzer is None:
            raise HTTPException(503, "No signal analyzer: start the app with --analyzer <its address>.")
        if req.dac not in board.calibration.dac_full_scale_dbm:
            raise HTTPException(422, f"No DAC called {req.dac}.")
        try:
            new = session.measure(x_client_id, lambda b: calibrate_dac_with_analyzer(
                b, analyzer, b.calibration, req.dac, req.cable_loss_db), None)
        except NotController as e:
            raise HTTPException(403, str(e))
        except Busy as e:
            raise HTTPException(409, str(e))
        except (ValueError, ScpiError) as e:
            raise HTTPException(422, str(e))
        save_board(profiles_dir, new)
        board.calibration = new
        return new.model_dump()

    @app.post("/api/drive-power")
    def drive_power(run: RunRequest):
        """dBm hints for the gain fields of a measurement's form, as typed (not validated)."""
        profile = load_profiles(profiles_dir).get(run.chip)
        m = MEASUREMENTS.get(run.measurement)
        if profile is None or m is None or not hasattr(m, "drive_fields"):
            return {}
        return drive_hints(m, profile, run.params, board.calibration)

    @app.post("/api/iq-delay")
    def iq_delay(profile: SetupProfile, x_client_id: str = Header()):
        """Measure how far the Q DAC runs ahead of the I DAC, on the scope; the page fills the field."""
        if scope is None:
            raise HTTPException(503, "No oscilloscope is connected to the app.")
        try:
            return session.measure(x_client_id, lambda b: measure_iq_delay(b, scope, profile), profile)
        except NotController as e:
            raise HTTPException(403, str(e))
        except Busy as e:
            raise HTTPException(409, str(e))
        except (ValueError, FrequencyError, LoError) as e:
            raise HTTPException(422, str(e))
        except (RuntimeError, Pyro4.errors.PyroError) as e:  # the scope itself failed
            raise HTTPException(502, str(e))

    @app.post("/api/tone/off")
    def tone_off(x_client_id: str = Header()):
        try:
            session.tone_off(x_client_id)
        except NotController as e:
            raise HTTPException(403, str(e))
        return session.state()

    @app.post("/api/runs/stop")
    def stop_run(x_client_id: str = Header()):
        try:
            session.stop(x_client_id)
        except NotController as e:
            raise HTTPException(403, str(e))
        return session.state()

    @app.websocket("/ws")
    async def live(ws: WebSocket):
        await ws.accept()
        loop, queue = asyncio.get_running_loop(), asyncio.Queue()
        listener = lambda message: loop.call_soon_threadsafe(queue.put_nowait, message)
        session.subscribe(listener)
        try:
            await ws.send_json(session.state())
            if session.last_update:
                await ws.send_json(session.last_update)
            while True:
                await ws.send_json(await queue.get())
        except WebSocketDisconnect:
            pass
        finally:
            session.unsubscribe(listener)

    app.mount("/", _RevalidatedStaticFiles(directory=STATIC, html=True), name="page")
    return app


class _RevalidatedStaticFiles(StaticFiles):
    """The page's files, which browsers must check for a newer version on every load (a cheap 304 when
    unchanged); otherwise they may keep showing the old page after the app is updated."""

    def file_response(self, *args, **kwargs):
        response = super().file_response(*args, **kwargs)
        response.headers["Cache-Control"] = "no-cache"
        return response
