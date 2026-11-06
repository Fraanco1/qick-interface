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


@pytest.mark.parametrize("measurement", ["two_tone", "rabi"])
def test_qubit_measurements_wait_500_us_between_shots_set_in_the_measurement_not_the_chip(client, measurement):
    delay = client.get("/api/measurements").json()[measurement]["params"]["properties"]["final_delay_us"]

    assert delay["default"] == 500.0
    assert "from_chip" not in delay


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
    from qick_interface.lo import KeysightLo
    cxg = FakeCxg()
    app = create_app(FakeBoard(SOCCFG, flat_response), data_dir=tmp_path / "data",
                     profiles_dir=tmp_path / "profiles", lo=KeysightLo("127.0.0.1", cxg.port))
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
    from qick_interface.lo import KeysightLo
    cxg = FakeCxg()
    app = create_app(FakeBoard(SOCCFG, flat_response), data_dir=tmp_path / "data",
                     profiles_dir=tmp_path / "profiles", lo=KeysightLo("127.0.0.1", cxg.port))
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


def run_with_lo(tmp_path, cxg, lo_mhz, lo_power_dbm=13.0):
    from qick_interface.lo import KeysightLo
    app = create_app(FakeBoard(SOCCFG, flat_response), data_dir=tmp_path / "data",
                     profiles_dir=tmp_path / "profiles", lo=KeysightLo("127.0.0.1", cxg.port))
    with TestClient(app) as client:
        client.post("/api/control", headers=as_client("alice"))
        setup = {**LOOPBACK, "chip": "LO", "lo_mhz": lo_mhz, "lo_power_dbm": lo_power_dbm}
        client.put("/api/profiles/LO", json=setup, headers=as_client("alice"))
        sweep = {"measurement": "resonator_sweep", "chip": "LO",
                 "params": {"rf_start_mhz": lo_mhz + 100, "rf_stop_mhz": lo_mhz + 200, "points": 11, "rounds": 1}}
        return client.post("/api/runs", json=sweep, headers=as_client("alice"))


def test_the_lo_range_is_the_connected_generators_own(tmp_path):
    from fake_cxg import FakeCxg
    exg = FakeCxg(model="N5173B", freq_range_hz=(9e3, 20e9), power_range_dbm=(-135.0, 30.0))

    response = run_with_lo(tmp_path, exg, lo_mhz=12000.0)

    assert response.status_code == 200
    assert exg.freq_hz == 12e9 and exg.output


def test_an_lo_beyond_the_generators_range_names_the_generator(tmp_path):
    from fake_cxg import FakeCxg
    exg = FakeCxg(model="N5173B", freq_range_hz=(9e3, 20e9), power_range_dbm=(-135.0, 30.0))

    response = run_with_lo(tmp_path, exg, lo_mhz=21000.0)

    assert response.status_code == 422
    assert "N5173B" in response.text and "20000 MHz" in response.text
    assert not exg.output


def test_the_lo_power_stops_at_the_mixers_limit_even_if_the_generator_goes_higher(client):
    from fake_cxg import FakeCxg
    from qick_interface.lo import KeysightLo, LoError
    exg = FakeCxg(model="N5173B", freq_range_hz=(9e3, 20e9), power_range_dbm=(-135.0, 30.0))

    with pytest.raises(LoError, match="16 dBm, the mixers' limit"):
        KeysightLo("127.0.0.1", exg.port).apply(6000.0, 20.0)
    assert not exg.output
    client.post("/api/control", headers=as_client("alice"))  # and the setup refuses it in the first place
    response = client.put("/api/profiles/Hot", json={**LOOPBACK, "chip": "Hot", "lo_mhz": 6000.0, "lo_power_dbm": 20.0},
                          headers=as_client("alice"))
    assert response.status_code == 422


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


def test_cw_time_and_the_oscilloscope_run_with_a_run_key_and_the_others_with_run_sweep(client):
    measurements = client.get("/api/measurements").json()

    assert {k: m["run_key"] for k, m in measurements.items()} == {
        "resonator_sweep": "Run sweep", "cw_time": "Run", "two_tone": "Run sweep", "rabi": "Run sweep",
        "rx_iq_cal": "Run sweep", "oscilloscope": "Run"}


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


def test_the_controller_measures_the_time_of_flight_of_the_setup_being_edited(tmp_path):
    def pulse_at_0_42_us(prog):
        f_s = SOCCFG["readouts"][prog.cfg["inputs"][0]]["f_output"]
        t = np.arange(int(prog.cfg["window_us"] * f_s)) / f_s
        return [1000.0 * ((t >= 0.42) & (t < 0.42 + prog.cfg["pulse_us"])) + 0j]
    app = create_app(FakeBoard(SOCCFG, pulse_at_0_42_us), data_dir=tmp_path / "data", profiles_dir=tmp_path / "profiles")
    with TestClient(app) as client:
        client.post("/api/control", headers=as_client("alice"))
        unsaved = {**LOOPBACK, "chip": "Not saved yet"}

        assert client.post("/api/time-of-flight", json=unsaved, headers=as_client("bob")).status_code == 403
        measured = client.post("/api/time-of-flight", json=unsaved, headers=as_client("alice")).json()

        assert measured["time_of_flight_us"] == pytest.approx(0.42, abs=0.005)


def test_the_controller_measures_the_q_delay_on_the_scope(tmp_path):
    from qick_interface.fake_scope import FakeScope
    board = FakeBoard(SOCCFG, flat_response)
    scope = FakeScope(board, {"DAC_A": ("CH1", 0.0), "DAC_B": ("CH3", 1550.0)})
    app = create_app(board, data_dir=tmp_path / "data", profiles_dir=tmp_path / "profiles", scope=scope)
    iq = {**LOOPBACK, "output_path": "iq", "i_dac": "DAC_A", "q_dac": "DAC_B"}
    with TestClient(app) as client:
        client.post("/api/control", headers=as_client("alice"))

        assert client.post("/api/iq-delay", json=iq, headers=as_client("bob")).status_code == 403
        measured = client.post("/api/iq-delay", json=iq, headers=as_client("alice")).json()

        assert measured["iq_delay_ps"] == pytest.approx(1550, abs=20)
        assert client.post("/api/iq-delay", json=LOOPBACK, headers=as_client("alice")).status_code == 422


def test_without_a_scope_the_q_delay_cannot_be_measured(client):
    client.post("/api/control", headers=as_client("alice"))
    iq = {**LOOPBACK, "output_path": "iq"}

    r = client.post("/api/iq-delay", json=iq, headers=as_client("alice"))

    assert r.status_code == 503
    assert "oscilloscope" in r.json()["detail"]


def test_the_board_calibration_starts_from_the_data_sheets_and_the_controller_can_add_tables(client):
    board = client.get("/api/board").json()
    assert board["dac"]["DAC_B"] == [] and board["datasheet"]["dac"][0] == [100, -1.1]

    board["dac"]["DAC_B"] = [{"points": [[100, -2.0], [4000, -4.0]], "source": "typed in"}]
    assert client.put("/api/board", json=board, headers=as_client("bob")).status_code == 403
    client.post("/api/control", headers=as_client("alice"))
    assert client.put("/api/board", json=board, headers=as_client("alice")).status_code == 200

    assert client.get("/api/board").json()["dac"]["DAC_B"][0]["source"] == "typed in"
    board["dac"]["DAC_B"].append({"points": [[100, -2.0]], "source": "typed in"})
    assert client.put("/api/board", json=board, headers=as_client("alice")).status_code == 422  # two of that name


NO_CALIBRATION = {**LOOPBACK, "calibrations": {"ADC_D": "none", "DAC_B": "none"}}


def test_a_chip_without_calibration_gets_its_powers_relative_to_full_scale(client, tmp_path):
    client.post("/api/control", headers=as_client("alice"))
    client.put("/api/profiles/Loopback", json=NO_CALIBRATION, headers=as_client("alice"))

    with client.websocket_connect("/ws") as viewer:
        viewer.receive_json()
        client.post("/api/runs", json=SWEEP, headers=as_client("alice"))
        messages = messages_until_idle(viewer)

    update = next(m for m in messages if m["type"] == "update")
    assert update["units"] == {"dBm": "dBFS", "mV": "% FS"}
    # flat_response: |I+jQ| = 0.5 at gain 1, so 20·log10(0.5 / FULL_SCALE_COUNTS) dBFS
    from qick_interface.power import FULL_SCALE_COUNTS
    assert update["traces"]["Power (dBm)"][0] == pytest.approx(20 * np.log10(0.5 / FULL_SCALE_COUNTS), abs=0.01)
    saved = next(m for m in messages if m["type"] == "saved")
    meta = json.loads((tmp_path / "data" / saved["file"]).with_suffix(".json").read_text())
    assert meta["calibration"]["ADC_D"] == "no calibration" and meta["calibration"]["DAC_A"] == "data sheet"
    hints = client.post("/api/drive-power", json={**SWEEP, "params": {**SWEEP["params"], "gain": 0.5}}).json()
    assert hints["gain"] == "≈ −6.0 dBFS at DAC_B (no calibration)"


def test_a_calibrated_run_says_its_units_are_dbm(client):
    client.post("/api/control", headers=as_client("alice"))
    client.put("/api/profiles/Loopback", json=LOOPBACK, headers=as_client("alice"))

    with client.websocket_connect("/ws") as viewer:
        viewer.receive_json()
        client.post("/api/runs", json=SWEEP, headers=as_client("alice"))
        update = next(m for m in messages_until_idle(viewer) if m["type"] == "update")

    assert update["units"] == {"dBm": "dBm", "mV": "mV"}


def test_a_run_whose_chosen_table_was_deleted_says_so(client):
    client.post("/api/control", headers=as_client("alice"))
    client.put("/api/profiles/Loopback", json={**LOOPBACK, "calibrations": {"ADC_D": "loopback, gone"}},
               headers=as_client("alice"))

    response = client.post("/api/runs", json=SWEEP, headers=as_client("alice"))

    assert response.status_code == 422 and "ADC_D" in response.text


def test_the_adc_is_calibrated_from_the_loopback(tmp_path):
    from qick_interface.power import FULL_SCALE_COUNTS, BoardCalibration

    def loopback_reads_5_dbm_full_scale(program):
        f = ResonatorSweep.if_axis(program)
        dbm = BoardCalibration().dac_dbm("DAC_B", f, program.get_pulse_param("probe", "gain"))
        return [FULL_SCALE_COUNTS * 10 ** ((dbm - 5.0) / 20) + 0j]

    app = create_app(FakeBoard(SOCCFG, loopback_reads_5_dbm_full_scale), data_dir=tmp_path / "d", profiles_dir=tmp_path / "p")
    with TestClient(app) as client:
        client.post("/api/control", headers=as_client("alice"))

        board = client.post("/api/board/adc-from-loopback", json={"dac": "DAC_B", "adc": "ADC_D"},
                            headers=as_client("alice")).json()
        again = client.post("/api/board/adc-from-loopback", json={"dac": "DAC_B", "adc": "ADC_D"},
                            headers=as_client("alice")).json()

        assert board["added"] == {"port": "ADC_D", "name": board["adc"]["ADC_D"][0]["source"]}
        assert board["adc"]["ADC_D"][0]["points"][0][1] == pytest.approx(5.0, abs=0.01)
        assert len(again["adc"]["ADC_D"]) == 2  # the first one is kept
        assert client.get("/api/board").json()["adc"] == again["adc"]


def test_the_loopback_trusts_the_dac_table_the_chip_chose(tmp_path):
    from qick_interface.power import FULL_SCALE_COUNTS

    def reads_full_scale(program):
        return [FULL_SCALE_COUNTS * program.get_pulse_param("probe", "gain") + 0 * ResonatorSweep.if_axis(program)]

    app = create_app(FakeBoard(SOCCFG, reads_full_scale), data_dir=tmp_path / "d", profiles_dir=tmp_path / "p")
    with TestClient(app) as client:
        client.post("/api/control", headers=as_client("alice"))

        board = client.post("/api/board/adc-from-loopback", json={"dac": "DAC_B", "adc": "ADC_D",
                            "calibrations": {"DAC_B": "none"}}, headers=as_client("alice")).json()

    assert board["adc"]["ADC_D"][0]["points"][0][1] == pytest.approx(0.0, abs=0.01)
    assert "no calibration" in board["adc"]["ADC_D"][0]["source"]


def test_gain_fields_get_their_drive_power_in_dbm(client):
    client.post("/api/control", headers=as_client("alice"))
    client.put("/api/profiles/Loopback", json=LOOPBACK, headers=as_client("alice"))

    hints = client.post("/api/drive-power", json={**SWEEP, "params": {**SWEEP["params"], "gain": 0.5}}).json()
    rabi = client.post("/api/drive-power", json={"measurement": "rabi", "chip": "Loopback", "params": {
        "qubit_freq_mhz": 100.0, "readout_freq_mhz": 550.0, "readout_gain": 0.5, "scope_gain": 0.5}}).json()

    assert hints["gain"] == "≈ −7.1 dBm at DAC_B (data sheet)"  # at the sweep center, 150 MHz: −1.09 dBm full scale, −6.02 dB
    assert rabi["readout_gain"] == "≈ −7.0 dBm at DAC_B (data sheet)"
    assert rabi["scope_gain"] == "≈ −13.1 dBm peak at DAC_B (data sheet)"  # a Gaussian peaks 6 dB lower


def test_a_saved_board_calibration_is_not_taken_for_a_chip(client):
    client.post("/api/control", headers=as_client("alice"))
    client.put("/api/profiles/Loopback", json=LOOPBACK, headers=as_client("alice"))
    client.put("/api/board", json=client.get("/api/board").json(), headers=as_client("alice"))

    assert list(client.get("/api/profiles").json()) == ["Loopback"]


def test_a_calibration_saved_by_the_first_version_is_moved_out_of_the_chips(tmp_path):
    from qick_interface.power import BoardCalibration
    old = BoardCalibration()
    old.adc_full_scale_dbm["ADC_D"].source = "loopback, first version"
    (tmp_path / "profiles").mkdir()
    (tmp_path / "profiles" / "board.json").write_text(old.model_dump_json())

    app = create_app(FakeBoard(SOCCFG, flat_response), data_dir=tmp_path / "data", profiles_dir=tmp_path / "profiles")
    with TestClient(app) as client:
        assert client.get("/api/profiles").json() == {}
        assert client.get("/api/board").json()["adc"]["ADC_D"][0]["source"] == "loopback, first version"
    assert not (tmp_path / "profiles" / "board.json").exists()


def test_gaussian_edges_drive_6_db_below_a_flat_pulse_at_the_same_gain(client):
    # QICK plays a flat_top's flat part at half the gain, to match its ramps
    client.post("/api/control", headers=as_client("alice"))
    client.put("/api/profiles/Loopback", json=LOOPBACK, headers=as_client("alice"))
    dbm = lambda hint: float(hint.split()[1].replace("−", "-"))

    def qubit_gain_hint(shape):
        return client.post("/api/drive-power", json={"measurement": "rabi", "chip": "Loopback", "params": {
            "sweep": "length", "shape": shape, "qubit_freq_mhz": 100.0, "readout_freq_mhz": 550.0,
            "qubit_gain": 0.5}}).json()["qubit_gain"]

    assert dbm(qubit_gain_hint("flat")) - dbm(qubit_gain_hint("gaussian edges")) == pytest.approx(6.02, abs=0.1)  # hints have one decimal
    assert "peak" not in qubit_gain_hint("gaussian edges")  # the flat part is the level


def test_the_oscilloscope_is_listed_and_redraws_until_stop(client):
    oscilloscope = client.get("/api/measurements").json()["oscilloscope"]

    assert oscilloscope["name"] == "Oscilloscope" and oscilloscope["run_key"] == "Run"
    fields = oscilloscope["params"]["properties"]
    assert fields["qubit_freq_mhz"]["shown_when"] == {"qubit_pulse": ["flat", "gaussian", "gaussian edges"]}
    assert fields["readout_freq_mhz"]["from_chip"] == "readout_freq_mhz"


def test_only_the_oscilloscope_offers_a_horizontal_scale(client):
    measurements = client.get("/api/measurements").json()

    assert {k for k, m in measurements.items() if m["x_scale"]} == {"oscilloscope"}


def test_the_dac_calibration_needs_an_analyzer(client):
    client.post("/api/control", headers=as_client("alice"))

    assert client.get("/api/instruments").json()["analyzer"] is None
    response = client.post("/api/board/dac-from-analyzer", json={"dac": "DAC_A", "cable_loss_db": 0.5},
                           headers=as_client("alice"))
    assert response.status_code == 503 and "--analyzer" in response.text


def test_the_dac_is_calibrated_with_the_analyzer_and_kept(tmp_path, monkeypatch):
    from fake_pxa import FakePxa
    from qick_interface import power
    from qick_interface.analyzer import KeysightAnalyzer
    monkeypatch.setattr(power, "DAC_CAL_MHZ", np.array([100.0, 2000.0]))  # the full grid: test_power.py
    board = FakeBoard(SOCCFG, flat_response)

    def level(center_mhz):  # −1.5 dBm reaches the analyzer while a tone plays at its centre frequency
        playing = board.playing
        f = playing.get_pulse_param("tone", "freq") if playing is not None else None
        return -1.5 if f is not None and abs(f - center_mhz) < 0.01 else -95.0
    pxa = FakePxa(level)
    app = create_app(board, data_dir=tmp_path / "data", profiles_dir=tmp_path / "profiles",
                     analyzer=KeysightAnalyzer("127.0.0.1", pxa.port))
    with TestClient(app) as client:
        assert client.get("/api/instruments").json()["analyzer"] == "N9032B"
        request = {"dac": "DAC_A", "cable_loss_db": 0.5}
        assert client.post("/api/board/dac-from-analyzer", json=request, headers=as_client("bob")).status_code == 403
        client.post("/api/control", headers=as_client("alice"))

        response = client.post("/api/board/dac-from-analyzer", json=request, headers=as_client("alice"))

        assert response.status_code == 200
        kept = client.get("/api/board").json()["dac"]["DAC_A"][-1]
    assert all(dbm == pytest.approx(-1.0) for _, dbm in kept["points"])  # −1.5 read + 0.5 of cable
    assert "N9032B" in kept["source"]
    assert json.loads((tmp_path / "profiles" / "board" / "calibration.json").read_text())["dac"]["DAC_A"][-1] == kept
    assert pxa.continuous and board.playing is None  # the analyzer sweeps again, the DAC is silent


def test_the_analyzer_reads_fresh_sweeps_and_gives_back_its_trace_mode():
    # the lab PXA was left in Max Hold: every reading was the oldest peak (a flat −7.65 dBm table)
    from fake_pxa import FakePxa
    from qick_interface.analyzer import KeysightAnalyzer
    pxa = FakePxa(lambda f: -1.0, trace_type="MAXH")
    analyzer = KeysightAnalyzer("127.0.0.1", pxa.port)

    analyzer.prepare()
    assert pxa.trace_type == "WRIT"  # clear/write while measuring
    analyzer.peak_dbm(1000.0)
    analyzer.release()
    assert pxa.trace_type == "MAXH" and pxa.continuous  # as it was found


def test_a_marker_outside_the_span_stops_the_measurement():
    from fake_pxa import FakePxa
    from qick_interface.analyzer import AnalyzerError, KeysightAnalyzer
    pxa = FakePxa(lambda f: -7.65, marker_x_mhz=149.4)  # the marker the lab PXA showed
    analyzer = KeysightAnalyzer("127.0.0.1", pxa.port)
    analyzer.prepare()

    with pytest.raises(AnalyzerError, match="149.4 MHz"):
        analyzer.peak_dbm(4900.0)
