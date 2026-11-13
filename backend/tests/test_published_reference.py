import hashlib
import json
import subprocess
import sys

import pytest
from fastapi.testclient import TestClient

from gridsense import published_reference
from gridsense.api import create_app
from gridsense.ieee13 import ROOT, validate_reference


def test_official_column_correction_preserves_frozen_legacy_dataset():
    legacy_raw = ROOT.joinpath("reference.json").read_bytes()
    assert hashlib.sha256(legacy_raw).hexdigest() == (
        "44bd63ba5edbf8ab7a2f6d9b77008ec36017940f676a06c0472bbb24aed544f9"
    )
    legacy = json.loads(legacy_raw)
    corrected = json.loads(published_reference.REFERENCE.read_bytes())
    differences = {
        node
        for node, target in legacy["voltages_pu"].items()
        if corrected["voltages_pu"][node] != target
    }
    assert differences == {"692.3"}
    assert legacy["voltages_pu"]["692.3"] == 0.9777
    assert corrected["voltages_pu"]["692.3"] == 0.9778
    assert corrected["tolerance_pu"] == legacy["tolerance_pu"] == 0.003
    assert len(corrected["voltages_pu"]) == 29


def test_corrected_reference_uses_unchanged_native_default_solution():
    legacy = validate_reference()
    corrected = published_reference.validate_published_reference()
    assert corrected["converged"] and corrected["passed"]
    assert len(corrected["rows"]) == 29
    assert all(row["passed"] for row in corrected["rows"])
    assert {row["node"]: row["actual_pu"] for row in corrected["rows"]} == pytest.approx(
        {row["node"]: row["actual_pu"] for row in legacy["rows"]}, abs=1e-12
    )
    assert corrected["solver_version"] == legacy["solver_version"]


def test_modified_reference_is_rejected_before_native_execution(tmp_path, monkeypatch):
    reference = tmp_path / "modified.json"
    data = json.loads(published_reference.REFERENCE.read_bytes())
    data["voltages_pu"]["692.3"] = 0.9777
    reference.write_text(json.dumps(data))
    monkeypatch.setattr(published_reference, "REFERENCE", reference)
    monkeypatch.setattr(published_reference, "context", lambda: pytest.fail("Executed solver"))
    with pytest.raises(ValueError, match="dataset fingerprint changed"):
        published_reference.validate_published_reference()


def test_non_finite_native_reference_cannot_report_success(monkeypatch):
    original = published_reference.phase_voltages

    def invalid(ctx):
        return {**original(ctx), "692.3": float("inf")}

    monkeypatch.setattr(published_reference, "phase_voltages", invalid)
    with pytest.raises(ValueError, match="must be finite"):
        published_reference.validate_published_reference()


def test_browser_api_and_cli_use_corrected_official_reference(tmp_path):
    with TestClient(create_app(tmp_path)) as client:
        response = client.get("/api/verification/reference")
        assert response.status_code == 200
        api = response.json()
    proc = subprocess.run(
        [sys.executable, "-m", "gridsense.cli", "validate-feeder"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 0, proc.stderr
    cli = json.loads(proc.stdout)
    for result in (api, cli):
        assert result["configuration"] == "ieee13-published-official-reference-v2"
        assert result["passed"]
        row = next(row for row in result["rows"] if row["node"] == "692.3")
        assert row["published_pu"] == 0.9778
