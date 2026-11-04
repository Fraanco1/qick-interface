"""One board, one controller, many viewers (ADR 0003).

A single worker thread owns the board and runs one run at a time. Every change is
broadcast as a plain dict to subscribed listeners (the WebSocket clients).
"""
import threading
from collections.abc import Callable
from pathlib import Path

import numpy as np

from .storage import save_run


class NotController(PermissionError):
    pass


class Busy(RuntimeError):
    pass


class Session:
    def __init__(self, board, measurements: dict, data_dir: Path):
        self._board = board
        self._data_dir = data_dir
        self._measurements = measurements
        self._lock = threading.Lock()
        self._start_lock = threading.Lock()
        self._listeners: list[Callable[[dict], None]] = []
        self._worker: threading.Thread | None = None
        self._stop = threading.Event()
        self.controller: str | None = None
        self.controller_name: str | None = None
        self.tone: dict | None = None  # calibration tone currently playing
        self.last_update: dict | None = None

    # --- listeners ---------------------------------------------------------
    def subscribe(self, listener: Callable[[dict], None]) -> None:
        with self._lock:
            self._listeners.append(listener)

    def unsubscribe(self, listener: Callable[[dict], None]) -> None:
        with self._lock:
            self._listeners.remove(listener)

    def broadcast(self, message: dict) -> None:
        with self._lock:
            listeners = list(self._listeners)
        for listener in listeners:
            try:
                listener(message)
            except Exception:
                pass  # a closed connection must not stop the run for everyone

    def state(self) -> dict:
        return {"type": "state", "controller": self.controller, "controller_name": self.controller_name,
                "running": self.running, "tone": self.tone}

    @property
    def running(self) -> bool:
        return self._worker is not None and self._worker.is_alive()

    # --- control -----------------------------------------------------------
    def take_control(self, client_id: str, name: str | None = None) -> None:
        self.controller, self.controller_name = client_id, name
        self.broadcast(self.state())

    def _check_controller(self, client_id: str) -> None:
        if client_id != self.controller:
            raise NotController("Only the controller can do this. Take control first.")

    # --- runs --------------------------------------------------------------
    def start(self, client_id: str, measurement: str, profile, params: dict) -> None:
        self._check_controller(client_id)
        m = self._measurements[measurement]
        parsed = m.Params(**params)
        with self._start_lock:  # two quick clicks must not start two runs
            if self.running:
                raise Busy("A run is already in progress.")
            self._silence()
            self._stop.clear()
            self._worker = threading.Thread(target=self._run, args=(measurement, m, profile, parsed),
                                            daemon=True)
            self._worker.start()

    def play_tone(self, client_id: str, program, settings: dict) -> None:
        """Leave a calibration tone playing until tone_off() or the next run."""
        self._check_controller(client_id)
        with self._start_lock:
            if self.running:
                raise Busy("Stop the run before playing a calibration tone.")
            self._board.play(program)
            self.tone = settings
        self.broadcast(self.state())

    def tone_off(self, client_id: str) -> None:
        self._check_controller(client_id)
        self._silence()
        self.broadcast(self.state())

    def _silence(self) -> None:
        if self.tone is not None:
            self._board.silence()
            self.tone = None

    def stop(self, client_id: str) -> None:
        """Ask the run to end after the current round."""
        self._check_controller(client_id)
        self._stop.set()

    def _run(self, key, m, profile, params) -> None:
        self.broadcast({**self.state(), "running": True})
        u, failed = None, False
        try:
            for u in m.run(self._board, profile, params, self._stop.is_set):
                self.last_update = {"type": "update", "measurement": key, "chip": profile.chip,
                                    "round": u.round, "rounds": u.rounds, "x": _json_array(u.x),
                                    "traces": {k: _json_array(v) for k, v in u.traces.items()},
                                    "x_axis": u.x_axis or m.x_axis, "info": u.info}
                self.broadcast(self.last_update)
        except Exception as e:
            failed = True
            self.broadcast({"type": "error", "message": str(e)})
        finally:
            if u is not None:
                # a continuous run (rounds=None) ends normally when stopped
                completed = not failed and (u.rounds is None or u.round == u.rounds)
                self._save(key, profile, params, u, completed)
            self._worker = None
            self.broadcast(self.state())

    def _save(self, key, profile, params, u, completed: bool) -> None:
        try:
            rel = save_run(self._data_dir, key, profile, params, u, completed=completed)
            self.broadcast({"type": "saved", "file": rel})
        except Exception as e:
            self.broadcast({"type": "error", "message": f"Could not save the run: {e}"})


def _json_array(a) -> list:
    """Array as a JSON list; NaN and ±inf become null, which the page draws as a gap."""
    a = np.asarray(a, dtype=float)
    return np.where(np.isfinite(a), a, None).tolist()
