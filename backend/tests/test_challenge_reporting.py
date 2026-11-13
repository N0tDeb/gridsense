"""Study evidence must retain all cases and independently account for outcomes."""

import importlib
import importlib.util
import json
import shutil
from datetime import datetime, timezone
from pathlib import Path

import pytest


@pytest.fixture
def study(tmp_path, monkeypatch):
    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[2] / "experiments"))
    runner = importlib.import_module("run_session_challenge")
    protocol = tmp_path / "protocol.json"
    protocol.write_text(
        json.dumps(
            {
                "horizon_s": 2,
                "policies": ["off", "nominal", "guarded"],
                "control": {},
                "measurements": {},
                "cases": [{"id": "healthy", "pair": "control", "events": []}],
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(runner, "PROTOCOL", protocol)
    monkeypatch.setattr(runner, "FREEZE", tmp_path / "freeze.json")
    runner.FREEZE.write_text(
        json.dumps(
            {
                "frozen_at": datetime.now(timezone.utc).isoformat(),
                "fingerprints": runner.fingerprints(),
            }
        ),
        encoding="utf-8",
    )
    output = tmp_path / "study"
    runner.run(output)
    return runner, output


def test_report_checks_native_frames_and_refuses_to_overwrite(study):
    runner, output = study
    assert runner.verify_report(output)["episodes"] == 3
    with pytest.raises(ValueError, match="empty output"):
        runner.run(output)


@pytest.mark.parametrize("damage", ["denominator", "physical", "summary", "table", "source"])
def test_corrupted_study_cannot_pass_consistency(study, damage):
    runner, output = study
    path = output / "results.json"
    report = json.loads(path.read_text(encoding="utf-8"))
    if damage == "denominator":
        report["rows"].pop()
    elif damage == "physical":
        report["rows"][0]["outcome"]["feasible_critical_served_kwh"] += 1
    elif damage == "summary":
        report["summary"]["off"]["unserved_kwh"] += 1
    elif damage == "source":
        report["freeze"]["fingerprints"]["episode_sha256"] = "foreign"
    else:
        (output / "outcomes.csv").write_text("case,policy\n", encoding="utf-8")
    path.write_text(json.dumps(report), encoding="utf-8")
    with pytest.raises(ValueError):
        runner.verify_report(output)


def test_unknown_and_final_samples_do_not_receive_interval_service_credit(monkeypatch):
    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[2] / "experiments"))
    from run_session_challenge import physical_accounting

    electrical = {
        "feasible": True,
        "requested_kw": 720,
        "served_kw": 720,
        "critical_served_kw": 360,
        "unserved_kw": 0,
    }
    frames = [
        {"at_s": t, "electrical": e, "actuation_events": []}
        for t, e in enumerate([electrical, None, {**electrical, "feasible": False}])
    ]
    result = physical_accounting(frames)
    assert result["served_kwh"] == result["feasible_served_kwh"] == 0.2
    assert result["known_seconds"] == result["unknown_seconds"] == 1
    assert result["violation_ticks"] == 1 and result["violation_seconds"] == 0


def discovery_checker():
    path = Path(__file__).resolve().parents[2] / "scripts/check_challenge_discovery.py"
    spec = importlib.util.spec_from_file_location("discovery_checker_test", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_discovery_accounting_uses_retained_helper_without_current_source(tmp_path, monkeypatch):
    checker = discovery_checker()
    monkeypatch.setattr(checker, "ROOT", tmp_path / "absent-current-source")
    result = checker.verify_discovery()
    assert result["episodes"] == 75
    assert result["current_controller_replay"] is False


def test_discovery_rejects_changed_archived_helper(tmp_path, monkeypatch):
    checker = discovery_checker()
    archive = tmp_path / "archive"
    shutil.copytree(checker.ARCHIVE, archive)
    monkeypatch.setattr(checker, "ARCHIVE", archive)
    helper = archive / "source/run_session_benchmark.py.txt"
    helper.write_bytes(helper.read_bytes() + b"\n")
    with pytest.raises(ValueError, match="frozen discovery source"):
        checker.verify_discovery()
