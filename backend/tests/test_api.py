import json
import re
from pathlib import Path
import pyarrow as pa
import pyarrow.parquet as pq
import pytest
from fastapi.testclient import TestClient
from gridsense.api import create_app


@pytest.fixture(scope="module")
def client(tmp_path_factory):
    with TestClient(create_app(tmp_path_factory.mktemp("api"))) as c:
        yield c


def test_readiness_performed_a_real_dss_solve(client):
    response = client.get("/api/health")
    assert response.status_code == 200
    assert "OpenDSS" in response.json()["solver_version"]


def test_incident_create_retrieve_export_review_and_replay(client):
    response = client.post("/api/incidents", json={})
    assert response.status_code == 201
    incident = response.json()
    path = f"/api/incidents/{incident['id']}"
    assert client.get(path).json() == incident
    assert client.get(path + "/export").json() == incident
    assert client.get("/api/incidents").json()[0]["id"] == incident["id"]
    assert client.post(path + "/replay").json()["matched"]
    review = client.post(
        path + "/reviews",
        json={"verdict": "questioned", "note": "Check the stale measurement range."},
    )
    assert review.status_code == 201
    client.post(
        path + "/reviews", json={"verdict": "accepted", "note": "Reviewed the electrical result."}
    )
    assert len(client.get(path + "/reviews").json()) == 2
    assert client.get(path).json() == incident  # reviews do not rewrite history


@pytest.mark.parametrize(
    "payload",
    [
        {"load_b": -1},
        {"telemetry_age_s": 0},
        {"policy": "magic"},
        {"arbitrary_dss_command": "Clear"},
        {"title": "x" * 101},
    ],
)
def test_invalid_scenarios_fail_validation(client, payload):
    assert client.post("/api/incidents", json=payload).status_code == 422


def test_missing_resources_and_unknown_api_paths(client):
    assert client.get("/api/incidents/missing").status_code == 404
    assert (
        client.post("/api/incidents/missing/reviews", json={"verdict": "accepted"}).status_code
        == 404
    )
    assert client.get("/api/unknown").status_code == 404
    assert client.post("/api/unknown", json={}).status_code == 404
    schema = client.get("/openapi.json").json()
    operation_ids = [
        operation["operationId"]
        for path in schema["paths"].values()
        for method, operation in path.items()
        if method in {"get", "post"}
    ]
    assert len(operation_ids) == len(set(operation_ids))
    assert "/api/{path}" not in schema["paths"]
    documented = set(
        re.findall(
            r"\| `(GET|POST) ([^`]+)` \|",
            (Path(__file__).resolve().parents[2] / "docs/API.md").read_text(encoding="utf-8"),
        )
    )
    public = {
        (method.upper(), path)
        for path, operations in schema["paths"].items()
        for method in operations
        if method in {"get", "post"}
    }
    assert documented == public


def test_sweep_exports_roundtrip_with_manifest(client):
    response = client.post("/api/sweeps", json={"points": 3})
    assert response.status_code == 201
    sweep = response.json()
    export = client.get(f"/api/sweeps/{sweep['id']}/export?format=parquet")
    table = pq.read_table(pa.BufferReader(export.content))
    assert table.num_rows == 9
    assert json.loads(table.schema.metadata[b"gridsense_manifest"])["manifest"] == sweep["manifest"]
    assert client.get(f"/api/sweeps/{sweep['id']}/export").json() == sweep


def test_records_survive_application_restart(tmp_path):
    with TestClient(create_app(tmp_path)) as c:
        incident = c.post("/api/incidents", json={}).json()
    with TestClient(create_app(tmp_path)) as c:
        assert c.get(f"/api/incidents/{incident['id']}").json() == incident
