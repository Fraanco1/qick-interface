import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from qick import QickConfig

from qick_interface.board import FakeBoard
from qick_interface.measurements.resonator_sweep import ResonatorSweep
from qick_interface.server import create_app

SOCCFG = QickConfig(str(Path(__file__).parent / "fixtures" / "soccfg_rfsoc4x2.json"))


def flat_response(program):
    return [0.5 + 0 * ResonatorSweep.if_axis(program)]


@pytest.fixture
def client(tmp_path):
    app = create_app(FakeBoard(SOCCFG, flat_response), data_dir=tmp_path / "data",
                     profiles_dir=tmp_path / "profiles")
    with TestClient(app) as c:
        yield c


def test_lists_measurements_with_their_parameter_forms(client):
    measurements = client.get("/api/measurements").json()

    sweep = measurements["resonator_sweep"]
    assert sweep["name"] == "Resonator sweep"
    assert sweep["params"]["properties"]["rf_start_mhz"]["unit"] == "MHz"


LOOPBACK = {"chip": "Loopback", "chip_type": "transmon", "lo_mhz": None,
            "readout_dac": "DAC_B", "readout_adc": "ADC_D"}


def test_saved_setup_profiles_are_listed_back(client, tmp_path):
    assert client.put("/api/profiles/Loopback", json=LOOPBACK).status_code == 200

    profiles = client.get("/api/profiles").json()

    assert profiles["Loopback"]["readout_adc"] == "ADC_D"
    assert (tmp_path / "profiles" / "Loopback.json").exists()


SWEEP = {"measurement": "resonator_sweep", "chip": "Loopback",
         "params": {"rf_start_mhz": 100.0, "rf_stop_mhz": 200.0, "points": 101, "rounds": 3}}


def as_client(client_id):
    return {"X-Client-Id": client_id}


def test_only_the_controller_can_start_a_run(client):
    client.put("/api/profiles/Loopback", json=LOOPBACK)
    client.post("/api/control", headers=as_client("alice"))

    assert client.post("/api/runs", json=SWEEP, headers=as_client("bob")).status_code == 403

    client.post("/api/control", headers=as_client("bob"))
    assert client.post("/api/runs", json=SWEEP, headers=as_client("bob")).status_code == 200


def messages_until_idle(ws, already_running=False):
    """Collect WebSocket messages until a state message says the run has ended."""
    seen_running, messages = already_running, []
    while True:
        m = ws.receive_json()
        messages.append(m)
        seen_running |= m["type"] == "state" and m["running"]
        if seen_running and m["type"] == "state" and not m["running"]:
            return messages


def test_viewers_see_each_round_and_the_run_is_saved(client, tmp_path):
    client.put("/api/profiles/Loopback", json=LOOPBACK)
    client.post("/api/control", headers=as_client("alice"))

    with client.websocket_connect("/ws") as viewer:
        assert viewer.receive_json()["type"] == "state"
        client.post("/api/runs", json=SWEEP, headers=as_client("alice"))
        messages = messages_until_idle(viewer)

    rounds = [m["round"] for m in messages if m["type"] == "update"]
    assert rounds == [1, 2, 3]
    saved = next(m for m in messages if m["type"] == "saved")
    assert (tmp_path / "data" / saved["file"]).with_suffix(".npz").exists()
    assert (tmp_path / "data" / saved["file"]).with_suffix(".json").exists()


def test_stopping_a_run_saves_what_was_measured_as_incomplete(tmp_path):
    slow = FakeBoard(SOCCFG, flat_response, round_time_s=0.05)
    app = create_app(slow, data_dir=tmp_path / "data", profiles_dir=tmp_path / "profiles")
    with TestClient(app) as client:
        client.put("/api/profiles/Loopback", json=LOOPBACK)
        client.post("/api/control", headers=as_client("alice"))
        long_sweep = {**SWEEP, "params": {**SWEEP["params"], "rounds": 100}}

        with client.websocket_connect("/ws") as viewer:
            client.post("/api/runs", json=long_sweep, headers=as_client("alice"))
            while viewer.receive_json()["type"] != "update":
                pass
            assert client.post("/api/runs/stop", headers=as_client("alice")).status_code == 200
            messages = messages_until_idle(viewer, already_running=True)

    saved = next(m for m in messages if m["type"] == "saved")
    meta = json.loads((tmp_path / "data" / saved["file"]).with_suffix(".json").read_text())
    assert meta["completed"] is False
    assert meta["rounds_done"] < 100


def test_invalid_parameters_are_rejected_with_a_reason(client):
    client.put("/api/profiles/Loopback", json=LOOPBACK)
    client.post("/api/control", headers=as_client("alice"))
    bad = {**SWEEP, "params": {**SWEEP["params"], "points": 1}}

    response = client.post("/api/runs", json=bad, headers=as_client("alice"))

    assert response.status_code == 422
    assert "points" in response.text
