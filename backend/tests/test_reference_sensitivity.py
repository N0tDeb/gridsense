"""Native controls isolate constitutive assumptions from solve precision."""

import copy
import json
import subprocess
import sys
from pathlib import Path

import pytest

from gridsense import ieee13


@pytest.fixture(scope="module")
def study():
    import sys

    sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "experiments"))
    import run_reference_sensitivity

    return run_reference_sensitivity, run_reference_sensitivity.run_study()


def test_native_controls_match_load_law_and_preserve_default_model(study):
    _, report = study
    rows = {row["configuration"]: row for row in report["rows"]}
    original, combined = rows["native-defaults"], rows["combined"]
    assert report["diagnostic_controls_matched"]
    assert not report["native_default_reference_passed"]
    native = original["load_675b"]
    settings = original["effective_settings"]
    assert native["voltage_on_load_base_pu"] > settings["vmaxpu"]
    expected = (
        settings["nominal_kw"] * (native["voltage_on_load_base_pu"] / settings["vmaxpu"]) ** 2
    )
    assert native["actual_kw"] == pytest.approx(expected, abs=0.05)
    assert (
        combined["load_675b"]["voltage_on_load_base_pu"] < combined["effective_settings"]["vmaxpu"]
    )
    assert combined["load_675b"]["actual_kw"] == pytest.approx(settings["nominal_kw"], abs=0.05)
    assert combined["passed_checks"] == combined["total_checks"] == 56
    assert max(abs(v) for v in combined["balance"]["residual_kw_kvar"]) < 1e-5
    ctx = ieee13.context()
    ctx.Loads.Name("675b")
    assert ctx.Loads.Vmaxpu() == 1.05
    assert ctx.Solution.Convergence() == 1e-4


@pytest.mark.parametrize("damage", ["baseline-status", "counts", "targets"])
def test_saved_diagnostic_cannot_relabel_baseline_or_forge_results(study, damage):
    runner, actual = study
    saved = copy.deepcopy(actual)
    if damage == "baseline-status":
        saved["native_default_reference_passed"] = True
    elif damage == "counts":
        saved["rows"][0]["passed_checks"] = 56
    else:
        saved["frozen_targets_and_tolerances"]["power_tolerance_kw_kvar"] = 2.0
    with pytest.raises(ValueError, match="differs from actual native"):
        runner.compare_reports(saved, actual)


@pytest.mark.parametrize(
    "field,value",
    [
        ("actual", float("inf")),
        ("actual", float("-inf")),
        ("actual", float("nan")),
        ("tolerance", float("inf")),
        ("balance", float("inf")),
    ],
)
def test_saved_diagnostic_rejects_nonfinite_measurements_and_allowances(study, field, value):
    runner, actual = study
    saved = copy.deepcopy(actual)
    if field == "balance":
        saved["rows"][0]["balance"]["residual_kw_kvar"][0] = value
    else:
        saved["rows"][0]["checks"][0][field] = value
    with pytest.raises(ValueError, match="non-finite"):
        runner.compare_reports(saved, actual)


@pytest.mark.parametrize("token", ["Infinity", "-Infinity", "NaN", "1e999", "-1e999"])
def test_diagnostic_cli_rejects_nonfinite_json_and_numeric_overflow(study, tmp_path, token):
    _, actual = study
    saved = copy.deepcopy(actual)
    saved["rows"][0]["checks"][0]["actual"] = "invalid-numeric-token"
    source = tmp_path / "altered-report.json"
    source.write_text(json.dumps(saved).replace('"invalid-numeric-token"', token), encoding="utf-8")
    result = subprocess.run(
        [
            sys.executable,
            str(Path(__file__).resolve().parents[2] / "experiments/run_reference_sensitivity.py"),
            "--verify-report",
            str(source),
        ],
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 2
    assert "non-finite" in result.stderr and "Traceback" not in result.stderr
    assert not result.stdout
