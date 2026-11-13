import sqlite3
import time

import pytest
from fastapi.testclient import TestClient
from gridsense.api import create_app
from gridsense.episodes import EpisodeConfig
from gridsense.session_store import CreateSession, SessionMutation, SessionStore


@pytest.fixture(scope="module")
def client(tmp_path_factory):
    with TestClient(create_app(tmp_path_factory.mktemp("session-api"))) as client:
        yield client


def test_session_api_step_retry_export_and_replay_use_native_workers(client):
    response = client.post(
        "/api/sessions", json={"request_id": "api-create", "config": {"horizon_s": 2}}
    )
    assert response.status_code == 201
    first = response.json()
    path = "/api/sessions/" + first["id"]
    request = {"request_id": "api-step", "expected_revision": 0, "operation": "step"}
    stepped = client.post(path + "/actions", json=request)
    assert stepped.status_code == 200 and stepped.json()["at_s"] == 1
    assert client.post(path + "/actions", json=request).json() == stepped.json()
    assert (
        client.post(path + "/actions", json={**request, "request_id": "stale"}).status_code == 409
    )
    assert "simulation" not in client.get(path).json()
    truth = client.get(path + "/simulation").json()
    assert truth["simulation"]["electrical"]["converged"]
    assert truth["simulation"]["electrical"]["served_kw"] == pytest.approx(2550, abs=0.001)
    export = client.get(path + "/export")
    assert export.status_code == 200 and "attachment" in export.headers["content-disposition"]
    assert len(export.json()["frames"]) == 2
    assert client.post(path + "/replay").json()["matched"]
    assert any(r["id"] == first["id"] for r in client.get("/api/sessions").json())


def test_actual_background_playback_reaches_horizon_and_stops(client):
    first = client.post(
        "/api/sessions", json={"request_id": "api-play", "config": {"horizon_s": 2}}
    ).json()
    path = "/api/sessions/" + first["id"]
    response = client.post(
        path + "/actions",
        json={"request_id": "play", "expected_revision": 0, "operation": "play", "rate": 10},
    )
    assert response.status_code == 200 and response.json()["mode"] == "running"
    deadline = time.monotonic() + 20
    view = response.json()
    while view["mode"] == "running" and time.monotonic() < deadline:
        time.sleep(0.05)
        view = client.get(path).json()
    assert view["at_s"] == 2 and view["mode"] == "paused"
    assert view["pause_reason"] == "Episode horizon reached"
    assert [f["at_s"] for f in client.get(path + "/export").json()["frames"]] == [0, 1, 2]
    assert client.post(path + "/replay").json()["matched"]


@pytest.mark.parametrize(
    "config",
    [
        {"horizon_s": 0},
        {"horizon_s": 601},
        {"horizon_s": True},
        {"measurements": {"latency_s": 31}},
        {"arbitrary_command": "Clear"},
    ],
)
def test_api_rejects_invalid_session_definitions(client, config):
    response = client.post("/api/sessions", json={"request_id": "invalid", "config": config})
    assert response.status_code == 422


def test_missing_session_and_invalid_actions(client):
    for suffix in ("", "/simulation", "/export"):
        assert client.get("/api/sessions/missing" + suffix).status_code == 404
    assert client.post("/api/sessions/missing/replay").status_code == 404
    assert (
        client.post(
            "/api/sessions/missing/actions",
            json={"request_id": "a", "expected_revision": 0, "operation": "step"},
        ).status_code
        == 404
    )
    for operation in (
        {"operation": "rate"},
        {"operation": "schedule"},
        {"operation": "play", "rate": 9},
    ):
        assert (
            client.post(
                "/api/sessions/missing/actions",
                json={"request_id": "a", "expected_revision": 0, **operation},
            ).status_code
            == 422
        )


def test_application_startup_pauses_saved_playback_without_advancing(tmp_path):
    store = SessionStore(tmp_path / "gridsense.sqlite3")
    first = store.create(CreateSession(request_id="start", config=EpisodeConfig(horizon_s=2)))
    store.mutate(
        first["id"], SessionMutation(request_id="play", expected_revision=0, operation="play")
    )
    with TestClient(create_app(tmp_path)) as client:
        view = client.get("/api/sessions/" + first["id"]).json()
        assert view["at_s"] == 0 and view["mode"] == "paused" and view["revision"] == 2
        assert client.post("/api/sessions/" + first["id"] + "/replay").json()["matched"]


def test_storage_read_error_is_reported_as_unavailable(client, monkeypatch):
    def fail(*args, **kwargs):
        raise sqlite3.OperationalError("unavailable")

    monkeypatch.setattr(client.app.state.sessions, "read", fail)
    assert client.get("/api/sessions/any").status_code == 503


def test_controlled_session_native_workers_confirm_restore_and_recover(client):
    response = client.post(
        "/api/sessions",
        json={
            "request_id": "controlled-api",
            "config": {
                "horizon_s": 7,
                "control": {"policy": "nominal"},
                "events": [
                    {
                        "kind": "outage",
                        "at_s": 1,
                        "incident_id": "trip",
                        "equipment_kind": "line",
                        "equipment": "feed_a",
                    },
                    {"kind": "repair", "at_s": 4, "incident_id": "trip"},
                ],
            },
        },
    )
    assert response.status_code == 201
    receipt = response.json()
    path = "/api/sessions/" + receipt["id"]
    for i in range(7):
        response = client.post(
            path + "/actions",
            json={
                "request_id": "step-" + str(i),
                "expected_revision": receipt["revision"],
                "operation": "step",
            },
        )
        assert response.status_code == 200
        receipt = response.json()
    public = client.get(path).json()
    assert public["control"]["supply_status"] == "normal_supply_verified"
    assert len(public["control"]["commands"]) == 3
    assert "actuators" not in public and "feedback" not in public
    assert client.post(path + "/replay").json()["matched"]
