import json
import subprocess
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from gridsense.api import create_app
from gridsense.cases import PortableCase, RegressionInput, presets
from gridsense.domain import Action, Operation
from gridsense.ieee13 import context, validate_reference
from gridsense.plants import plant_for, planning_view
from gridsense.regression import (
    checksum,
    evaluate_case,
    replay_regression,
    rerun_regression,
    run_regression,
)
from gridsense.service import implementation_hash
from gridsense.temporal import (
    DeviceEvent,
    TemporalInput,
    run_temporal,
    replay_temporal,
    simulate_events,
)


@pytest.mark.parametrize("fixture", ["foreign-regression-a.json", "foreign-regression-b.json"])
def test_foreign_build_exports_are_rejected(fixture):
    # Authentic records from different builds exercise strict source identity.
    path = Path(__file__).parent / "fixtures" / fixture
    previous = json.loads(path.read_text(encoding="utf-8"))
    with pytest.raises(ValueError, match="Historical replay"):
        replay_regression(previous)
    assert implementation_hash() != previous["manifest"]["legacy_implementation_sha256"]


def test_regression_requires_service_and_safety():
    record = run_regression(RegressionInput())
    assert record["accepted"] and record["candidate"]["passed"]
    assert not record["baseline"]["electrical_pass"]
    assert record["baseline"]["action"]["id"] == "tie_b"
    assert record["candidate"]["action"]["id"] == "tie_c"
    hold = run_regression(RegressionInput(candidate="hold-v1"))
    assert hold["candidate"]["electrical_pass"] and not hold["candidate"]["service_pass"]
    assert not hold["accepted"] and "Lower restored_kw" in hold["regressions"]


def test_custom_controller_has_no_hidden_demand_and_needs_no_engine_edit():
    class Probe:
        id = "external-probe-v1"

        def select(self, view):
            self.view = view
            return next(c.action for c in view.candidates if c.action.id == "hold")

    probe = Probe()
    case = PortableCase()
    result = evaluate_case(case, probe)
    first = probe.view
    changed = case.model_copy(update={"scenario": case.scenario.model_copy(update={"load_b": 1.5})})
    evaluate_case(changed, probe)
    assert first == probe.view
    assert result["controller"] == probe.id and not result["service_pass"]


def test_unadvertised_switch_sequence_is_rejected():
    class Malformed:
        id = "invalid"

        def select(self, view):
            return Action(
                id="hold", label="injected", operations=(Operation(line="feed_a", closed=True),)
            )

    with pytest.raises(ValueError, match="outside"):
        evaluate_case(PortableCase(), Malformed())


def test_current_evaluation_accepts_old_version_but_strict_replay_does_not():
    previous = run_regression(RegressionInput())
    previous["manifest"]["harness_sha256"] = "a-different-older-controller-build"
    previous["content_sha256"] = checksum(previous)
    with pytest.raises(ValueError, match="Historical replay"):
        replay_regression(previous)
    current = rerun_regression(previous, "hold-v1")
    assert current["baseline"] == previous["candidate"]
    assert current["historical_baseline"]["source_record_id"] == previous["id"]
    assert not current["accepted"]
    assert replay_regression(current)["matched"]
    previous["candidate"]["result"]["restored_kw"] = 0
    with pytest.raises(ValueError, match="integrity"):
        rerun_regression(previous, "guarded-v1")


def test_independent_reference_and_phase_equipment_are_preserved():
    result = validate_reference()
    assert result["passed"] and len(result["rows"]) == 29
    assert result["max_error_pu"] < 0.003
    ctx = context()
    ctx.Solution.Solve()
    ctx.Circuit.SetActiveBus("645")
    assert set(ctx.Bus.Nodes()) == {2, 3}
    ctx.Circuit.SetActiveBus("611")
    assert ctx.Bus.Nodes() == [3]
    assert len(ctx.Loads.AllNames()) == 15 and len(ctx.Capacitors.AllNames()) == 2
    ctx.Transformers.Name("reg3")
    ctx.Transformers.Wdg(2)
    assert ctx.Transformers.Tap() == pytest.approx(1.06875)


def test_external_feeder_restoration_uses_native_phase_limits():
    case = PortableCase.model_validate(presets()[2])
    result = run_regression(RegressionInput(case=case))
    assert result["accepted"] and result["candidate"]["action"]["id"] == "backup_rg"
    assert result["candidate"]["result"]["restored_kw"] > 750
    assert "675.3" in result["candidate"]["result"]["voltages_pu"]
    assert replay_regression(result)["matched"]
    # Higher demand overloads a transformer in this published circuit.
    # Its phase-current limit must still be enforced.
    changed = case.model_copy(
        update={
            "scenario": case.scenario.model_copy(
                update={"load_a": 1.0, "load_b": 1.0, "reported_b": 1.0}
            )
        }
    )
    plant = plant_for(changed)
    assert any(v.element == "xfm1" for v in plant.solve(plant.truth).violations)


@pytest.mark.parametrize("fault", ["632670", "671692"])
def test_external_fault_stays_open_for_every_candidate(fault):
    case = PortableCase.model_validate({**presets()[2], "fault": fault})
    plant = plant_for(case)
    for candidate in planning_view(plant, "2026-01-01T12:00:00+00:00").candidates:
        outcome = plant.execute(plant.truth, candidate.action)
        assert fault not in outcome.final_state.closed_lines
        assert outcome.result.line_loading_pct[fault] == 0


def event_case(delay, fail=True):
    events = [DeviceEvent(kind="delay_confirmation", delay_s=delay)]
    if fail:
        events.append(DeviceEvent(kind="fail_close"))
    return simulate_events(TemporalInput(), events)


def test_failed_actuator_and_delayed_confirmation_are_real_states():
    result = event_case(12)
    assert result["is_failure"] and result["final_electrical"]["restored_kw"] == 0
    command = next(r for r in result["trace"] if r["event"] == "command")
    assert command["commanded_closed"] and not command["physical_closed"]
    assert command["trackers"]["confirmed-v2"]["status"] == "pending"
    timeout = next(r for r in result["trace"] if r["event"] == "timeout")
    assert "unknown" in timeout["trackers"]["confirmed-v2"]["status"]
    assert timeout["trackers"]["optimistic-v1"]["status"] == "restored"
    assert result["trace"][-1]["trackers"]["confirmed-v2"]["status"] == "failed"
    assert all(f["controller"] == "optimistic-v1" for f in result["failures"])


def test_event_boundary_feedback_precedes_timeout_and_success_is_solved():
    assert not event_case(4)["is_failure"]
    assert event_case(5)["is_failure"]
    success = event_case(12, False)
    assert not success["is_failure"] and success["final_electrical"]["restored_kw"] > 990
    assert success["unserved_energy_kwh"] > 0
    assert success["trace"][-1]["trackers"]["confirmed-v2"]["status"] == "restored"


def test_event_search_reduction_and_replay_preserve_failure():
    request = TemporalInput(budget=4)
    first = run_temporal(request)
    second = run_temporal(request)
    assert first["trials"] == second["trials"]
    assert first["reduction"]["reduced_complexity"] == (2, 5)
    assert first["reduced"]["is_failure"] and replay_temporal(first)["matched"]
    for i in range(2):
        reduced = first["reduced"]["events"]
        events = [DeviceEvent.model_validate(e) for e in reduced[:i] + reduced[i + 1 :]]
        assert not simulate_events(request, events)["is_failure"]


def test_verification_api_persistence_export_replay_and_rerun(tmp_path):
    with TestClient(create_app(tmp_path)) as client:
        result = client.post("/api/verification/regressions", json={})
        assert result.status_code == 201
        record = result.json()
        url = "/api/verification/records/" + record["id"]
        assert client.get(url + "/export").json() == record
        assert client.post(url + "/replay").json()["matched"]
        rerun = client.post(url + "/rerun", json={"candidate": "hold-v1"})
        assert rerun.status_code == 201 and not rerun.json()["accepted"]
        assert client.get("/api/verification/reference").json()["passed"]
        assert (
            client.post(
                "/api/verification/regressions", json={"case": {"fault": "unknown"}}
            ).status_code
            == 422
        )
        assert client.get("/api/verification/records/missing").status_code == 404
        temporal = client.post("/api/verification/temporal", json={"budget": 1, "seed": 42})
        assert temporal.status_code == 201 and temporal.json()["status"] == "failure_found"
        assert client.post("/api/verification/records/" + temporal.json()["id"] + "/replay").json()[
            "matched"
        ]
    with TestClient(create_app(tmp_path)) as client:
        assert client.get(url).json() == record
        assert len(client.get("/api/verification/records").json()) == 3


def test_cli_current_regression_then_strict_verification(tmp_path):
    path = tmp_path / "case.json"
    proc = subprocess.run(
        [
            sys.executable,
            "-m",
            "gridsense.cli",
            "regress",
            "--data-dir",
            str(tmp_path),
            "--output",
            str(path),
        ],
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 0, proc.stderr
    record = json.loads(path.read_text())
    assert record["accepted"]
    proc = subprocess.run(
        [sys.executable, "-m", "gridsense.cli", "verify-run", "--file", str(path)],
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 0 and json.loads(proc.stdout)["matched"]
    proc = subprocess.run(
        [
            sys.executable,
            "-m",
            "gridsense.cli",
            "regress",
            "--file",
            str(path),
            "--candidate",
            "hold-v1",
            "--data-dir",
            str(tmp_path),
        ],
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 1 and not json.loads(proc.stdout)["accepted"]
