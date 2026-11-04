"""FastAPI app: REST + WebSocket + the static page. No measurement logic here."""
from pathlib import Path

import asyncio
from urllib.parse import unquote

from fastapi import FastAPI, Header, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ValidationError

from .tone import OutputTone, tone_program
from .frequency import FrequencyError
from .measurements.cw_time import CwTime
from .measurements.resonator_sweep import ResonatorSweep
from .measurements.rabi import Rabi
from .measurements.rx_iq_cal import RxIqCal
from .measurements.two_tone import TwoTone
from .profiles import ChipParameters, SetupProfile, load_parameters, load_profiles, save_profile, update_parameters
from .session import Busy, NotController, Session

STATIC = Path(__file__).parent / "static"
MEASUREMENTS = {"resonator_sweep": ResonatorSweep, "cw_time": CwTime, "two_tone": TwoTone, "rabi": Rabi,
                "rx_iq_cal": RxIqCal}


class RunRequest(BaseModel):
    measurement: str
    chip: str
    params: dict


def create_app(board, data_dir: Path, profiles_dir: Path) -> FastAPI:
    app = FastAPI(title="QICK interface")
    session = Session(board, MEASUREMENTS, data_dir)
    app.state.session = session

    @app.get("/api/measurements")
    def measurements():
        return {key: {"name": m.name, "params": m.Params.model_json_schema(), "x_axis": m.x_axis,
                      "plots": m.plots, "marker_sets": m.marker_sets, "info_sets": m.info_sets,
                      "setup_sets": getattr(m, "setup_sets", {}), "setup_label": getattr(m, "setup_label", "")}
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
        return session.state()

    @app.post("/api/tone")
    def tone_on(tone: OutputTone, x_client_id: str = Header()):
        profile = load_profiles(profiles_dir).get(tone.chip)
        if profile is None:
            raise HTTPException(404, f"No setup profile for chip {tone.chip!r}.")
        try:
            session.play_tone(x_client_id, tone_program(board.soccfg, profile, tone), tone.model_dump())
        except NotController as e:
            raise HTTPException(403, str(e))
        except Busy as e:
            raise HTTPException(409, str(e))
        except FrequencyError as e:
            raise HTTPException(422, str(e))
        return session.state()

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

    app.mount("/", StaticFiles(directory=STATIC, html=True), name="page")
    return app
