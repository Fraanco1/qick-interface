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
    client.post("/api/control", headers=as_client("alice"))
    assert client.put("/api/profiles/Loopback", json=LOOPBACK, headers=as_client("alice")).status_code == 200

    profiles = client.get("/api/profiles").json()

    assert profiles["Loopback"]["readout_adc"] == "ADC_D"
    assert (tmp_path / "profiles" / "Loopback.json").exists()


SWEEP = {"measurement": "resonator_sweep", "chip": "Loopback",
         "params": {"rf_start_mhz": 100.0, "rf_stop_mhz": 200.0, "points": 101, "rounds": 3}}


def as_client(client_id):
    return {"X-Client-Id": client_id}


def test_only_the_controller_can_start_a_run(client):
    client.post("/api/control", headers=as_client("alice"))
    client.put("/api/profiles/Loopback", json=LOOPBACK, headers=as_client("alice"))

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
    client.post("/api/control", headers=as_client("alice"))
    client.put("/api/profiles/Loopback", json=LOOPBACK, headers=as_client("alice"))

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
        client.post("/api/control", headers=as_client("alice"))
        client.put("/api/profiles/Loopback", json=LOOPBACK, headers=as_client("alice"))
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
    client.post("/api/control", headers=as_client("alice"))
    client.put("/api/profiles/Loopback", json=LOOPBACK, headers=as_client("alice"))
    bad = {**SWEEP, "params": {**SWEEP["params"], "points": 1}}

    response = client.post("/api/runs", json=bad, headers=as_client("alice"))

    assert response.status_code == 422
    assert "points" in response.text


def test_only_the_controller_can_change_a_setup_profile(client):
    client.post("/api/control", headers=as_client("alice"))

    assert client.put("/api/profiles/Loopback", json=LOOPBACK, headers=as_client("bob")).status_code == 403
    assert client.put("/api/profiles/Loopback", json=LOOPBACK, headers=as_client("alice")).status_code == 200


def test_points_without_signal_reach_viewers_as_gaps(tmp_path):
    def dead_input(program):
        return [0 * ResonatorSweep.if_axis(program) + 0j]

    app = create_app(FakeBoard(SOCCFG, dead_input), data_dir=tmp_path / "data", profiles_dir=tmp_path / "profiles")
    with TestClient(app) as client:
        client.post("/api/control", headers=as_client("alice"))
        client.put("/api/profiles/Loopback", json=LOOPBACK, headers=as_client("alice"))
        with client.websocket_connect("/ws") as viewer:
            viewer.receive_json()
            client.post("/api/runs", json=SWEEP, headers=as_client("alice"))
            update = next(m for m in messages_until_idle(viewer) if m["type"] == "update")

    assert update["traces"]["|S21| (dB)"][0] is None


IQ_SETUP = {"chip": "Transmon A", "chip_type": "transmon", "lo_mhz": 6800.0, "output_path": "iq",
            "i_dac": "DAC_A", "q_dac": "DAC_B"}


def test_controller_plays_an_iq_calibration_tone_and_turns_it_off(tmp_path):
    board = FakeBoard(SOCCFG, flat_response)
    app = create_app(board, data_dir=tmp_path / "data", profiles_dir=tmp_path / "profiles")
    with TestClient(app) as client:
        client.post("/api/control", headers=as_client("alice"))
        client.put("/api/profiles/Transmon A", json=IQ_SETUP, headers=as_client("alice"))
        tone = {"chip": "Transmon A", "rf_mhz": 7000.0, "gain": 0.3, "iq_phase_deg": 94.0, "iq_gain_ratio": 0.95}

        assert client.post("/api/tone", json=tone, headers=as_client("bob")).status_code == 403
        assert client.post("/api/tone", json=tone, headers=as_client("alice")).json()["tone"]["rf_mhz"] == 7000.0

        played = board.playing
        assert played.get_pulse_param("tone", "freq") == pytest.approx(200.0, abs=0.001)
        assert played.get_pulse_param("tone_q", "phase") - played.get_pulse_param("tone", "phase") == pytest.approx(94.0)
        assert played.get_pulse_param("tone_q", "gain") == pytest.approx(0.3 * 0.95, abs=1e-4)

        assert client.post("/api/tone/off", headers=as_client("alice")).json()["tone"] is None
        assert board.playing is None


def test_controller_records_chip_parameters_that_viewers_can_read(client):
    client.post("/api/control", headers=as_client("alice"))
    client.put("/api/profiles/Loopback", json=LOOPBACK, headers=as_client("alice"))

    assert client.patch("/api/parameters/Loopback", json={"readout_freq_mhz": 7012.5},
                        headers=as_client("bob")).status_code == 403
    client.patch("/api/parameters/Loopback", json={"readout_freq_mhz": 7012.5}, headers=as_client("alice"))
    client.patch("/api/parameters/Loopback", json={"qubit_freq_mhz": 10021.0}, headers=as_client("alice"))

    assert client.get("/api/parameters/Loopback").json() == {"readout_freq_mhz": 7012.5, "qubit_freq_mhz": 10021.0}


def test_each_measurement_says_which_chip_parameter_its_marker_sets(client):
    measurements = client.get("/api/measurements").json()

    assert measurements["resonator_sweep"]["marker_sets"] == "readout_freq_mhz"
    assert measurements["two_tone"]["marker_sets"] == "qubit_freq_mhz"
    readout = measurements["two_tone"]["params"]["properties"]["readout_freq_mhz"]
    assert readout["from_chip"] == "readout_freq_mhz"
