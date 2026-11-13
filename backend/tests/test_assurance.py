import copy
import json
import subprocess
import sys
from pathlib import Path

import pytest

from gridsense.assurance import (
    ExperimentalController,
    VARIANTS,
    assess_temporal_trace,
    classify,
    compare_episode,
    prepare_episode,
    reduce_episode,
    replay_defect,
)
from gridsense.cases import PortableCase
from gridsense.controllers import CONTROLLERS
from gridsense.domain import Scenario
from gridsense.reference_checks import derived_current, validate_extended_reference
from gridsense.regression import checksum, harness_hash
from gridsense.temporal import DeviceEvent, TemporalInput, simulate_events

ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture(scope="module")
def fresh():
    return PortableCase(
        scenario=Scenario(
            load_b=0.7, reported_b=0.7, load_c=1.1, telemetry_age_s=0, uncertainty_pct=0
        )
    )


def test_experiments_do_not_replace_production_or_trusted_harness():
    assert set(CONTROLLERS) == {"nominal-v1", "guarded-v1", "hold-v1"}
    protocol = json.loads(
        (ROOT / "experiments/protocols/assurance.json").read_text(encoding="utf-8")
    )
    assert harness_hash() == protocol["harness_sha256"]
    assert set(VARIANTS).isdisjoint(CONTROLLERS)
    with pytest.raises(ValueError, match="Unknown"):
        ExperimentalController("upload.py")


@pytest.mark.parametrize("variant", ["nominal-control", "guarded-control"])
def test_unmodified_controls_do_not_raise_false_detections(fresh, variant):
    pair = compare_episode(fresh, variant)
    assert pair["reference"]["passed"] and pair["candidate"]["passed"]
    assert not pair["detected"]
    assert pair["candidate"]["action"] == pair["reference"]["action"]


def test_real_solver_exposes_reversed_service_priority(fresh):
    pair = compare_episode(fresh, "reverse-service")
    assert pair["detected"] and pair["category"] == "service-contract-regression"
    assert pair["reference"]["result"]["restored_kw"] > 990
    assert pair["candidate"]["result"]["restored_kw"] == 0
    assert pair["candidate"]["electrical_pass"]


def test_baseline_failure_cannot_be_counted_as_a_detected_defect():
    assert not classify({"passed": False}, {"rejected": True})["detected"]
    assert (
        classify({"passed": True}, {"rejected": True})["category"] == "action-interface-rejection"
    )


def test_native_errors_are_not_silently_counted_as_mutations(fresh, monkeypatch):
    def fail(*args, **kwargs):
        raise ValueError("Solver adapter failure")

    monkeypatch.setattr(ExperimentalController, "select", fail)
    with pytest.raises(ValueError, match="Solver adapter failure"):
        compare_episode(fresh, "nominal-control")


def test_stale_truth_is_not_in_variant_view():
    case = PortableCase()
    another = case.model_copy(update={"scenario": case.scenario.model_copy(update={"load_b": 1.5})})
    first, second = prepare_episode(case), prepare_episode(another)
    assert first["view"] == second["view"]
    for name in VARIANTS:
        a, b = ExperimentalController(name), ExperimentalController(name)
        a.select(copy.deepcopy(first["prime_view"]))
        b.select(copy.deepcopy(second["prime_view"]))
        assert a.select(first["view"]) == b.select(second["view"])


def test_reduction_replays_both_cases_and_detects_tampering(fresh):
    record = reduce_episode(fresh, "reverse-service", budget=4)
    assert len(record["trials"]) <= 4
    assert record["complexity_after"] <= record["complexity_before"]
    assert record["original"]["category"] == record["reduced"]["category"]
    assert record["original_case"]["contract"] == record["reduced_case"]["contract"]
    assert replay_defect(record)["matched"]
    bad = copy.deepcopy(record)
    bad["reduced_case"]["scenario"]["load_c"] = 2
    with pytest.raises(ValueError, match="integrity"):
        replay_defect(bad)
    bad = copy.deepcopy(record)
    bad["manifest"]["assurance_sha256"] = "different-build"
    bad["content_sha256"] = checksum(bad)
    with pytest.raises(ValueError, match="implementation"):
        replay_defect(bad)
    bad = copy.deepcopy(record)
    bad["reduced"]["reference"]["result"]["restored_kw"] = 1
    bad["content_sha256"] = checksum(bad)
    assert not replay_defect(bad)["matched"]


def test_reducer_rejects_nonfailure_and_out_of_range_budget(fresh):
    with pytest.raises(ValueError, match="attributable"):
        reduce_episode(fresh, "nominal-control")
    with pytest.raises(ValueError, match="budget"):
        reduce_episode(fresh, "reverse-service", 65)


@pytest.mark.parametrize("failed", [False, True])
def test_status_variants_share_native_physics_but_only_receive_messages(failed):
    events = [DeviceEvent(kind="delay_confirmation", delay_s=12)]
    if failed:
        events.append(DeviceEvent(kind="fail_close"))
    simulation = simulate_events(TemporalInput(), events)
    before = copy.deepcopy(simulation)
    correct = assess_temporal_trace(simulation, "confirmed-control")
    assert not correct["detected"]
    for variant in ("optimistic-command", "timeout-success"):
        result = assess_temporal_trace(simulation, variant)
        assert result["detected"]  # Even successful closure was not yet confirmed at timeout.
        assert all(r["event"] in {"command", "position", "timeout"} for r in result["messages"])
    assert simulation == before


def test_confirmation_at_timeout_wins_the_documented_tie():
    simulation = simulate_events(
        TemporalInput(timeout_s=3), [DeviceEvent(kind="delay_confirmation", delay_s=2)]
    )
    assert not assess_temporal_trace(simulation, "timeout-success")["detected"]
    assert [r["event"] for r in simulation["trace"] if r["at_s"] == 4] == ["position", "timeout"]


def test_inverted_open_position_is_an_unsupported_restored_claim():
    simulation = simulate_events(TemporalInput(), [DeviceEvent(kind="fail_close")])
    broken = assess_temporal_trace(simulation, "inverted-position")
    assert broken["detected"] and broken["failures"][0]["event"] == "position"
    assert not broken["failures"][0]["received_closed"]
    assert broken["failures"][0]["actual_restored_kw"] == 0
    assert not assess_temporal_trace(simulation, "confirmed-control")["detected"]


def test_defect_cli_rejects_nonobject_without_a_traceback(tmp_path):
    path = tmp_path / "invalid.json"
    path.write_text("[]", encoding="utf-8")
    result = subprocess.run(
        [sys.executable, str(ROOT / "experiments/reproduce_assurance.py"), str(path)],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 2 and "JSON object" in result.stderr
    assert "Traceback" not in result.stderr


def test_verification_runner_preserves_existing_evidence(tmp_path):
    (tmp_path / "evidence.txt").write_text("retain me", encoding="utf-8")
    result = subprocess.run(
        [sys.executable, str(ROOT / "scripts/verify.py"), "--output-dir", str(tmp_path)],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 2 and "not empty" in result.stderr
    assert (tmp_path / "evidence.txt").read_text() == "retain me"


def test_current_formula_uses_published_voltage_not_the_solver_value():
    assert derived_current(
        {"kw": 3, "kvar": 4, "voltage_pu": 1, "base_ll_kv": 3**0.5}
    ) == pytest.approx(5)


def test_additional_reference_checks_preserve_evidence_categories():
    protocol = json.loads(
        (ROOT / "experiments/protocols/electrical.json").read_text(encoding="utf-8")
    )
    result = validate_extended_reference(protocol)
    # Keep the reference mismatch visible: Model=1 can switch from constant PQ
    # to impedance behavior outside its voltage range.
    assert not result["passed"]
    assert {r["id"] for r in result["additional_checks"] if not r["passed"]} == {
        "load-current-675b",
        "load-kw-675b",
        "load-kvar-675b",
        "power-balance-kW",
    }
    assert len(result["published_voltage"]["rows"]) == 29
    assert len(result["additional_checks"]) == 27
    assert (
        sum(r["category"] == "derived-from-published-values" for r in result["additional_checks"])
        == 11
    )
    assert (
        sum(
            r["category"] == "internal-consistency-not-external-validation"
            for r in result["additional_checks"]
        )
        == 2
    )
    diagnostics = result["post_hoc_diagnostics"]
    assert (
        diagnostics["native_675b"]["actual_pu_on_load_base"] > diagnostics["native_675b"]["vmaxpu"]
    )
    assert all(r["passed"] for r in diagnostics["fallback_formula_checks"])
    assert diagnostics["precision_control"]["balance_passed"]
    assert all(r["passed"] for r in diagnostics["constitutive_model_control"]["checks"])
    wrong = copy.deepcopy(protocol)
    wrong["loads"][0]["kw"] *= 2
    assert not validate_extended_reference(wrong)["passed"]
