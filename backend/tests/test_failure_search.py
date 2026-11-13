"""Failure discovery tests use native OpenDSS; curated domains are not benchmarks."""

import copy
import json
import random
import subprocess
import sys

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from gridsense.api import create_app
from gridsense.domain import Scenario
from gridsense.failure_search import (
    Bounds,
    SearchInput,
    SearchSpace,
    as_point,
    content_hash,
    describe,
    discover,
    preserves,
    reduce_case,
    replay_search,
    run_search,
    scenario_for,
    signature,
    simpler_neighbors,
    tick,
)
from gridsense.service import evaluate
from gridsense.storage import IncidentStore

AT = "2026-01-01T12:00:00+00:00"


def fixed_request(point, **kwargs):
    return SearchInput(
        bounds={k: Bounds(minimum=v, maximum=v) for k, v in point.items()},
        reference=point,
        budget=4,
        reduction_budget=0,
        **kwargs,
    )


@pytest.fixture(scope="module")
def failure_record():
    # Known stale-reading case, deliberately fixed for integration testing.
    return run_search(
        fixed_request(
            {"load_a": 1, "load_b": 1.5, "load_c": 0.9, "reported_b": 0.85}, uncertainty_pct=80
        )
    )


@pytest.mark.parametrize(
    "changes",
    [
        {"budget": 65},
        {"telemetry_age_s": 0},
        {"policy": "oracle"},
        {"bounds": {"load_a": {"minimum": 0.51, "maximum": 1}}},
        {"reference": {"load_a": 1, "load_b": 2, "load_c": 1, "reported_b": 0.5}},
        {"bounds": {"unexpected": {"minimum": 0.5, "maximum": 1}}},
    ],
)
def test_search_rejects_invalid_or_unbounded_requests(changes):
    with pytest.raises(ValidationError):
        SearchInput(**changes)


def test_seeded_sampler_is_unique_admissible_and_paired():
    space = SearchSpace(SearchInput())

    def sample(directed):
        rng, seen, points = random.Random(17), set(), []
        for i in range(32):
            point = space.next_point(rng, seen, points[0] if points else None, directed, i)
            assert point is not None and space.admissible(point) and point not in seen
            seen.add(point)
            points.append(point)
        return points

    assert sample(True) == sample(True)
    assert sample(True)[:4] == sample(False)[:4]


def test_failure_requires_a_feasible_alternative_and_valid_initial_state(failure_record):
    case = failure_record["original_incident"]
    finding = describe(case, "nominal")
    assert finding["is_failure"] and finding["truth_inside_assumed_range"]
    assert finding["feasible_alternative"]["action"] == "tie_c"
    assert finding["predicted_loading_pct"] < 100 < finding["actual_loading_pct"]
    invalid_start = copy.deepcopy(case)
    invalid_start["before"]["feasible"] = False
    assert describe(invalid_start, "nominal")["category"] == "pre_existing_violation"
    unconverged = copy.deepcopy(case)
    unconverged["outcomes"]["nominal"]["result"]["converged"] = False
    assert describe(unconverged, "nominal")["category"] == "solver_failure"
    busy = evaluate(Scenario(load_a=1.5, load_b=2, reported_b=0.5, load_c=2), AT)
    assert not busy["outcomes"]["nominal"]["result"]["feasible"]
    assert describe(busy, "nominal")["category"] == "no_feasible_restoration"


def test_assumption_breach_is_reported_separately(failure_record):
    point = failure_record["original_incident"]["scenario"]
    point = {k: point[k] for k in SearchInput().reference}
    request = fixed_request(point, uncertainty_pct=40, assumption_scope="unrestricted")
    finding = describe(evaluate(scenario_for(request, point), AT), "nominal")
    assert finding["is_failure"] and not finding["truth_inside_assumed_range"]


def test_reduction_re_solves_and_preserves_the_physical_failure(failure_record):
    request = SearchInput(uncertainty_pct=80, reduction_budget=48)
    original = failure_record["original_incident"]
    report, reduced = reduce_case(request, original)
    assert tuple(report["reduced_complexity"]) < tuple(report["original_complexity"])
    assert report["evaluations"] <= request.reduction_budget
    assert preserves(
        describe(reduced, request.policy), signature(describe(original, request.policy))
    )
    previous = tuple(report["original_complexity"])
    for row in report["trace"]:
        assert SearchSpace(request).admissible(
            tuple(tick(row["point"][k]) for k in request.reference)
        )
        if row["accepted"]:
            assert tuple(row["complexity"]) < previous
            previous = tuple(row["complexity"])
    # If the implementation claims its neighborhood is exhausted, independently
    # challenge every advertised simpler neighbor with the native evaluator.
    if report["neighborhood_exhausted"]:
        current = tuple(tick(reduced["scenario"][k]) for k in request.reference)
        reference = tuple(tick(request.reference[k]) for k in request.reference)
        for point in simpler_neighbors(current, reference):
            if SearchSpace(request).admissible(point):
                outcome = evaluate(scenario_for(request, as_point(point)), original["created_at"])
                assert not preserves(describe(outcome, request.policy), report["signature"])


def test_no_failure_and_finite_exhaustion_do_not_claim_safety():
    request = fixed_request({"load_a": 1, "load_b": 0.7, "load_c": 1.1, "reported_b": 0.7})
    result = run_search(request)
    assert result["status"] == "no_failure_found"
    for method in result["strategies"].values():
        assert method["space_exhausted"] and method["evaluations"] == 1
        assert method["first_failure_evaluation"] is None
    assert result["reduced_incident"] is None
    with pytest.raises(ValueError, match="did not find"):
        replay_search(result)


def test_real_search_traces_are_repeatable_without_changing_controller_inputs():
    request = SearchInput(budget=4, reduction_budget=0)
    first, _ = discover(request, "directed")
    second, _ = discover(request, "random")
    assert first["trace"] == second["trace"]
    assert first["evaluations"] == second["evaluations"] == 4


def test_reproduction_checks_controller_and_electrical_branches(failure_record):
    result = replay_search(failure_record)
    assert result["matched"] and not result["differences"]
    assert all(c["branches_checked"] == 5 for c in result["cases"].values())
    altered = copy.deepcopy(failure_record)
    altered["original_incident"]["decisions"]["nominal"]["rationale"] = "changed"
    altered["content_sha256"] = content_hash(altered)
    mismatch = replay_search(altered)
    assert not mismatch["matched"]
    assert any("decisions.nominal.rationale" in d for d in mismatch["differences"])


def test_reproduction_rejects_damage_and_incompatible_versions(failure_record):
    altered = copy.deepcopy(failure_record)
    altered["request"]["seed"] += 1
    with pytest.raises(ValueError, match="integrity"):
        replay_search(altered)
    altered["search_implementation_sha256"] = "different"
    altered["content_sha256"] = content_hash(altered)
    with pytest.raises(ValueError, match="implementation"):
        replay_search(altered)


def test_search_persistence_is_atomic_and_retains_existing_incidents(tmp_path, failure_record):
    store = IncidentStore(tmp_path / "test.sqlite")
    store.save_search(failure_record)
    assert len(store.list_incidents()) == 1  # unchanged reduction shares the ID
    # A duplicate search ID rolls back inserts of any new incident IDs too.
    duplicate = copy.deepcopy(failure_record)
    duplicate["original_incident"]["id"] = "new-unsaved-id"
    duplicate["reduced_incident"] = None
    import sqlite3

    with pytest.raises(sqlite3.IntegrityError):
        store.save_search(duplicate)
    assert len(store.list_incidents()) == 1
    assert IncidentStore(store.path).get_search(failure_record["id"]) == failure_record


def test_failure_search_api_creates_exports_replays_and_survives_restart(tmp_path, failure_record):
    with TestClient(create_app(tmp_path)) as client:
        response = client.post("/api/failure-searches", json=failure_record["request"])
        assert response.status_code == 201
        record = response.json()
        path = f"/api/failure-searches/{record['id']}"
        assert client.get(path).json() == record
        assert client.get(path + "/export").json() == record
        assert client.post(path + "/replay").json()["matched"]
        assert client.get("/api/failure-searches").json()[0]["id"] == record["id"]
        assert client.get(f"/api/incidents/{record['reduced_incident']['id']}").status_code == 200
        assert client.post("/api/failure-searches", json={"budget": 999}).status_code == 422
        assert client.get("/api/failure-searches/missing").status_code == 404
    with TestClient(create_app(tmp_path)) as client:
        assert client.get(path).json() == record


def test_export_is_a_headless_reproducer_with_meaningful_exit_codes(tmp_path, failure_record):
    path = tmp_path / "case.json"
    path.write_text(json.dumps(failure_record))
    command = [sys.executable, "-m", "gridsense.cli", "reproduce", "--file", str(path)]
    result = subprocess.run(command, cwd=tmp_path, capture_output=True, text=True)
    assert result.returncode == 0 and json.loads(result.stdout)["matched"]
    assert not (tmp_path / "var").exists()
    altered = copy.deepcopy(failure_record)
    altered["request"]["seed"] += 1
    path.write_text(json.dumps(altered))
    result = subprocess.run(command, cwd=tmp_path, capture_output=True, text=True)
    assert result.returncode == 2 and "integrity" in result.stderr
