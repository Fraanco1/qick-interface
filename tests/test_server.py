import json
from pathlib import Path

import numpy as np
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


LOOPBACK = {"chip": "Loopback", "lo_mhz": None,
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


IQ_SETUP = {"chip": "Transmon A", "lo_mhz": 6800.0, "output_path": "iq",
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


def test_rabi_declares_its_plots_and_the_fit_result_it_can_store(client):
    rabi = client.get("/api/measurements").json()["rabi"]

    assert rabi["plots"][0]["traces"] == ["Signal", "Fit"]
    assert rabi["info_sets"] == {"π-pulse gain": "pi_gain"}


def test_controller_sends_a_tone_on_a_real_output_to_check_it_on_a_scope(tmp_path):
    board = FakeBoard(SOCCFG, flat_response)
    app = create_app(board, data_dir=tmp_path / "data", profiles_dir=tmp_path / "profiles")
    with TestClient(app) as client:
        client.post("/api/control", headers=as_client("alice"))
        client.put("/api/profiles/Loopback", json=LOOPBACK, headers=as_client("alice"))

        response = client.post("/api/tone", json={"chip": "Loopback", "rf_mhz": 500.0, "gain": 0.4},
                               headers=as_client("alice"))

        assert response.status_code == 200
        assert board.playing.pulses["tone"].params["mode"] == "periodic"
        assert board.playing.get_pulse_param("tone", "freq") == pytest.approx(500.0, abs=0.001)


def test_controller_plays_a_rabi_shot_on_repeat_to_check_its_pulses_on_a_scope(tmp_path):
    board = FakeBoard(SOCCFG, flat_response)
    app = create_app(board, data_dir=tmp_path / "data", profiles_dir=tmp_path / "profiles")
    with TestClient(app) as client:
        client.post("/api/control", headers=as_client("alice"))
        client.put("/api/profiles/Loopback", json=LOOPBACK, headers=as_client("alice"))
        params = {"qubit_freq_mhz": 400.0, "readout_freq_mhz": 150.0, "scope_gain": 0.3}

        response = client.post("/api/sequence", json={"measurement": "rabi", "chip": "Loopback", "params": params},
                               headers=as_client("alice"))

        assert response.status_code == 200
        assert response.json()["tone"]["mode"] == "sequence"
        assert board.playing.get_pulse_param("qubit", "gain") == pytest.approx(0.3, abs=0.001)
        client.post("/api/tone/off", headers=as_client("alice"))
        assert board.playing is None


def test_a_sequence_with_bad_parameters_is_refused_with_a_reason(client):
    client.post("/api/control", headers=as_client("alice"))
    client.put("/api/profiles/Loopback", json=LOOPBACK, headers=as_client("alice"))
    params = {"qubit_start_mhz": 300.0, "qubit_stop_mhz": 500.0, "readout_freq_mhz": 150.0}  # no qubit frequency

    response = client.post("/api/sequence", json={"measurement": "two_tone", "chip": "Loopback", "params": params},
                           headers=as_client("alice"))

    assert response.status_code == 422
    assert "Qubit frequency" in str(response.json()["detail"])


def test_cw_time_runs_until_stopped_and_saves_every_sweep(tmp_path):
    def flat_in_time(program):
        return [np.full(program.cfg["points"], 0.5, complex)]

    board = FakeBoard(SOCCFG, flat_in_time, round_time_s=0.02)
    app = create_app(board, data_dir=tmp_path / "data", profiles_dir=tmp_path / "profiles")
    with TestClient(app) as client:
        client.post("/api/control", headers=as_client("alice"))
        client.put("/api/profiles/Loopback", json=LOOPBACK, headers=as_client("alice"))
        cw_time = {"measurement": "cw_time", "chip": "Loopback", "params": {"freq_mhz": 150.0, "points": 51}}

        with client.websocket_connect("/ws") as viewer:
            client.post("/api/runs", json=cw_time, headers=as_client("alice"))
            updates = 0
            while updates < 3:
                m = viewer.receive_json()
                updates += m["type"] == "update"
            assert m["rounds"] is None  # no fixed end: it runs until Stop
            client.post("/api/runs/stop", headers=as_client("alice"))
            messages = messages_until_idle(viewer, already_running=True)

    saved = next(m for m in messages if m["type"] == "saved")
    name = tmp_path / "data" / saved["file"]
    meta = json.loads(name.with_suffix(".json").read_text())
    sweeps = meta["rounds_done"]
    assert sweeps >= 3
    assert meta["completed"] is True  # Stop is how a continuous run ends
    assert np.load(f"{name}.npz")["s21"].shape == (sweeps, 51)


def test_rx_calibration_says_which_setup_fields_its_results_can_be_stored_in(client):
    cal = client.get("/api/measurements").json()["rx_iq_cal"]

    assert cal["setup_sets"] == {"Q/I gain": "rx_gain_ratio", "Q phase (°)": "rx_phase_deg",
                                 "I/Q delay (ps)": "rx_delay_ps"}


def test_a_setup_with_an_iq_return_path_is_saved(client):
    client.post("/api/control", headers=as_client("alice"))
    iq_return = {**LOOPBACK, "return_path": "iq", "i_adc": "ADC_D", "q_adc": "ADC_C", "rx_delay_ps": 48.0}

    assert client.put("/api/profiles/Loopback", json=iq_return, headers=as_client("alice")).status_code == 200
    assert client.get("/api/profiles").json()["Loopback"]["rx_delay_ps"] == 48.0


def test_a_control_line_cannot_share_the_readout_dac(client):
    client.post("/api/control", headers=as_client("alice"))
    clash = {**LOOPBACK, "control_dac": "DAC_B"}  # the loopback reads out on DAC_B

    response = client.put("/api/profiles/Loopback", json=clash, headers=as_client("alice"))

    assert response.status_code == 422
    assert "control line" in response.text


def test_resonator_sweep_can_store_its_electrical_delay_in_the_setup(client):
    sweep = client.get("/api/measurements").json()["resonator_sweep"]

    assert sweep["setup_sets"] == {"Electrical delay (ns)": "electrical_delay_ns"}


def test_a_run_sets_the_lo_from_the_setup_and_leaves_it_on(tmp_path):
    from fake_cxg import FakeCxg
    from qick_interface.lo import CxgLo
    cxg = FakeCxg()
    app = create_app(FakeBoard(SOCCFG, flat_response), data_dir=tmp_path / "data",
                     profiles_dir=tmp_path / "profiles", lo=CxgLo("127.0.0.1", cxg.port))
    with TestClient(app) as client:
        client.post("/api/control", headers=as_client("alice"))
        transmon = {**LOOPBACK, "chip": "Transmon", "lo_mhz": 6000.0, "lo_power_dbm": 13.0}
        client.put("/api/profiles/Transmon", json=transmon, headers=as_client("alice"))
        sweep = {"measurement": "resonator_sweep", "chip": "Transmon",
                 "params": {"rf_start_mhz": 6900.0, "rf_stop_mhz": 7100.0, "points": 11, "rounds": 1}}

        with client.websocket_connect("/ws") as viewer:
            viewer.receive_json()
            assert client.post("/api/runs", json=sweep, headers=as_client("alice")).status_code == 200
            messages = messages_until_idle(viewer)

    assert (cxg.freq_hz, cxg.power_dbm, cxg.output, cxg.modulation) == (6e9, 13.0, True, False)
    assert messages[-1]["lo"] == {"freq_mhz": 6000.0, "power_dbm": 13.0, "on": True}


def test_an_lo_beyond_the_cxg_range_is_refused_before_the_run(tmp_path):
    from fake_cxg import FakeCxg
    from qick_interface.lo import CxgLo
    cxg = FakeCxg()
    app = create_app(FakeBoard(SOCCFG, flat_response), data_dir=tmp_path / "data",
                     profiles_dir=tmp_path / "profiles", lo=CxgLo("127.0.0.1", cxg.port))
    with TestClient(app) as client:
        client.post("/api/control", headers=as_client("alice"))
        high = {**LOOPBACK, "chip": "High", "lo_mhz": 6800.0}
        client.put("/api/profiles/High", json=high, headers=as_client("alice"))
        sweep = {"measurement": "resonator_sweep", "chip": "High",
                 "params": {"rf_start_mhz": 6900.0, "rf_stop_mhz": 7100.0, "points": 11, "rounds": 1}}

        response = client.post("/api/runs", json=sweep, headers=as_client("alice"))

    assert response.status_code == 422
    assert "6000 MHz" in response.text
    assert not cxg.output


def test_time_of_flight_is_part_of_the_setup_not_of_any_measurement(client):
    measurements = client.get("/api/measurements").json()

    assert all("trigger_delay_us" not in m["params"]["properties"] for m in measurements.values())
    client.post("/api/control", headers=as_client("alice"))
    client.put("/api/profiles/Loopback", json={**LOOPBACK, "time_of_flight_us": 0.29}, headers=as_client("alice"))
    assert client.get("/api/profiles").json()["Loopback"]["time_of_flight_us"] == 0.29


def test_profiles_saved_with_the_old_chip_type_field_still_load(client, tmp_path):
    (tmp_path / "profiles").mkdir()
    (tmp_path / "profiles" / "Old.json").write_text(json.dumps({"chip": "Old", "chip_type": "fluxonium"}))

    assert "chip_type" not in client.get("/api/profiles").json()["Old"]


def test_fields_say_when_they_apply(client):
    measurements = client.get("/api/measurements").json()
    sweep = measurements["resonator_sweep"]["params"]["properties"]
    rabi = measurements["rabi"]["params"]["properties"]

    assert sweep["pulse_length_us"]["shown_when"] == {"mode": "pulsed"}
    assert sweep["final_delay_us"]["shown_when"] == {"mode": "pulsed"}
    assert sweep["settle_us"]["shown_when"] == {"mode": "cw"}
    assert rabi["qubit_gain"]["shown_when"] == {"sweep": "length"}
    assert rabi["sigma_us"]["shown_when"] == {"sweep": "amplitude"}


def test_only_pulsed_qubit_measurements_offer_a_scope_sequence(client):
    measurements = client.get("/api/measurements").json()

    assert {k for k, m in measurements.items() if m["sequence"]} == {"two_tone", "rabi"}
    assert measurements["rabi"]["params"]["properties"]["scope_gain"]["group"] == "Output"


def test_cw_time_runs_with_a_run_key_and_the_others_with_run_sweep(client):
    measurements = client.get("/api/measurements").json()

    assert {k: m["run_key"] for k, m in measurements.items()} == {
        "resonator_sweep": "Run sweep", "cw_time": "Run", "two_tone": "Run sweep", "rabi": "Run sweep",
        "rx_iq_cal": "Run sweep"}


def test_rx_calibration_is_offered_only_for_an_iq_return_path(client):
    measurements = client.get("/api/measurements").json()

    assert measurements["rx_iq_cal"]["setup_requires"] == {"return_path": "iq"}
    assert measurements["resonator_sweep"]["setup_requires"] == {}


@pytest.mark.parametrize("path", ["/", "/app.js", "/style.css"])
def test_browsers_check_for_a_new_page_after_an_update(client, path):
    # without this, browsers keep showing the old page after the app is updated
    assert client.get(path).headers["cache-control"] == "no-cache"


def test_deleting_a_chip_removes_its_setup_and_parameters_but_keeps_its_runs(client, tmp_path):
    client.post("/api/control", headers=as_client("alice"))
    client.put("/api/profiles/Loopback", json=LOOPBACK, headers=as_client("alice"))
    client.patch("/api/parameters/Loopback", json={"readout_freq_mhz": 150.0}, headers=as_client("alice"))
    (tmp_path / "data").mkdir(exist_ok=True)
    (tmp_path / "data" / "run.npz").write_bytes(b"kept")

    assert client.delete("/api/profiles/Loopback", headers=as_client("alice")).status_code == 200

    assert "Loopback" not in client.get("/api/profiles").json()
    assert not (tmp_path / "profiles" / "parameters" / "Loopback.json").exists()
    assert (tmp_path / "data" / "run.npz").exists()
    client.put("/api/profiles/Loopback", json=LOOPBACK, headers=as_client("alice"))
    assert client.get("/api/parameters/Loopback").json() == {}  # a new chip of the same name starts clean


def test_only_the_controller_can_delete_a_chip(client):
    client.post("/api/control", headers=as_client("alice"))
    client.put("/api/profiles/Loopback", json=LOOPBACK, headers=as_client("alice"))

    assert client.delete("/api/profiles/Loopback", headers=as_client("bob")).status_code == 403
    assert "Loopback" in client.get("/api/profiles").json()


def test_deleting_an_unknown_chip_says_so(client):
    client.post("/api/control", headers=as_client("alice"))

    assert client.delete("/api/profiles/Nope", headers=as_client("alice")).status_code == 404


def test_a_two_tone_sequence_does_not_need_the_sweep_but_a_run_does(client):
    client.post("/api/control", headers=as_client("alice"))
    client.put("/api/profiles/Loopback", json=LOOPBACK, headers=as_client("alice"))
    params = {"readout_freq_mhz": 150.0, "scope_qubit_freq_mhz": 400.0}  # no Qubit start / stop

    sequence = client.post("/api/sequence", json={"measurement": "two_tone", "chip": "Loopback", "params": params},
                           headers=as_client("alice"))
    client.post("/api/tone/off", headers=as_client("alice"))
    run = client.post("/api/runs", json={"measurement": "two_tone", "chip": "Loopback", "params": params},
                      headers=as_client("alice"))

    assert sequence.status_code == 200
    assert run.status_code == 422
    assert "qubit_start_mhz" in str(run.json()["detail"])  # the page shows it as "Qubit start"
