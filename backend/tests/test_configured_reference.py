"""Same frozen targets, explicit changed model, and tamper-resistant evidence."""

import copy
import json
import subprocess
import sys
from pathlib import Path

import pytest

from gridsense import ieee13
from gridsense.configured_reference import validate_configured_reference

ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture(scope="module")
def reference():
    sys.path.insert(0, str(ROOT / "experiments"))
    import run_configured_reference

    return run_configured_reference, run_configured_reference.run_reference()


def test_versioned_profile_passes_the_identical_56_targets_without_changing_native_model(reference):
    _, result = reference
    baseline = result["native_default_baseline"]
    assert result["passed"] and result["passed_checks"] == result["total_checks"] == 56
    assert result["native_default_baseline_matched"]
    assert not baseline["passed"] and baseline["passed_checks"] == 52
    assert len(result["published_voltage"]["rows"]) == 29
    targets = lambda rows: [(row["id"], row["expected"], row["tolerance"]) for row in rows]
    assert targets(result["checks"]) == targets(baseline["checks"])
    assert result["effective_settings"]["vmaxpu"] == 1.1
    assert result["effective_settings"]["convergence_tolerance"] == 1e-8
    assert 1.05 < result["load_voltage_on_rated_base_pu"] < 1.1
    assert max(abs(v) for v in result["balance_components"]["residual_kw_kvar"]) < 1e-5
    ctx = ieee13.context()
    ctx.Loads.Name("675b")
    assert ctx.Loads.Vmaxpu() == 1.05 and ctx.Solution.Convergence() == 1e-4


@pytest.mark.parametrize("damage", ["name", "convergence", "load-window", "numeric-boolean"])
def test_profile_settings_require_an_explicit_version_change(reference, damage):
    _, result = reference
    profile = copy.deepcopy(result["profile"])
    if damage == "name":
        profile["configuration"] = "silent-retune"
    elif damage == "convergence":
        profile["convergence_tolerance"] = 1e-4
    elif damage == "load-window":
        profile["load_override"]["vmaxpu"] = 1.2
    else:
        profile["schema_version"] = True
    with pytest.raises(ValueError, match="declared v1"):
        validate_configured_reference(profile, result["protocol"])


def test_changed_published_power_fails_instead_of_using_a_solver_derived_target(reference):
    _, result = reference
    protocol = copy.deepcopy(result["protocol"])
    next(row for row in protocol["loads"] if row["name"] == "675b")["kw"] *= 2
    actual = validate_configured_reference(result["profile"], protocol)
    assert not actual["passed"]
    assert "load-kw-675b" in actual["failed_checks"]


@pytest.mark.parametrize("damage", ["count", "baseline", "boolean", "target", "tolerance"])
def test_saved_profile_cannot_forge_counts_baseline_or_frozen_checks(reference, damage):
    runner, actual = reference
    saved = copy.deepcopy(actual)
    if damage == "count":
        saved["passed_checks"] = 57
    elif damage == "baseline":
        saved["native_default_baseline"]["passed"] = True
    elif damage == "boolean":
        saved["checks"][0]["passed"] = 1
    elif damage == "target":
        saved["checks"][0]["expected"] *= 2
    else:
        saved["checks"][0]["tolerance"] *= 2
    with pytest.raises(ValueError, match="differs from actual native"):
        runner.compare_reports(saved, actual)


@pytest.mark.parametrize("token", ["Infinity", "1e999"])
def test_profile_cli_rejects_nonfinite_evidence_before_executing(reference, tmp_path, token):
    _, actual = reference
    saved = copy.deepcopy(actual)
    saved["checks"][0]["actual"] = "invalid-token"
    path = tmp_path / "altered.json"
    path.write_text(json.dumps(saved).replace('"invalid-token"', token), encoding="utf-8")
    result = subprocess.run(
        [
            sys.executable,
            str(ROOT / "experiments/run_configured_reference.py"),
            "--verify-report",
            str(path),
        ],
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 2
    assert "non-finite" in result.stderr and "Traceback" not in result.stderr
    assert not result.stdout


def test_cli_writes_and_strictly_rechecks_a_named_profile_without_overwriting(reference, tmp_path):
    runner, _ = reference
    path = tmp_path / "profile.json"
    command = [sys.executable, str(ROOT / "experiments/run_configured_reference.py")]
    saved = subprocess.run(
        [*command, "--output", str(path)], capture_output=True, text=True, timeout=30
    )
    assert saved.returncode == 0, saved.stderr
    report = json.loads(path.read_text(encoding="utf-8"))
    runner.compare_reports(report, runner.run_reference())
    rechecked = subprocess.run(
        [*command, "--verify-report", str(path)], capture_output=True, text=True, timeout=30
    )
    assert rechecked.returncode == 0, rechecked.stderr
    before = path.read_bytes()
    refused = subprocess.run(
        [*command, "--output", str(path)], capture_output=True, text=True, timeout=30
    )
    assert refused.returncode == 2 and "already exists" in refused.stderr
    assert path.read_bytes() == before
