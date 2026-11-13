"""Native equivalence, demand accounting and cache invalidation at disconnection."""

from copy import deepcopy
import json
from pathlib import Path

import pytest

from experiments.native_reuse_reference import FullDemandPredictor
from gridsense.electrical import ElectricalEngine, InvalidSwitching
from gridsense.episodes import EpisodeConfig, controller_view, start_episode
from gridsense.episodes import canonical_hash
from gridsense.restoration import BudgetExhausted, Predictor, demand_samples, planning_view
from gridsense.service import _differences
from gridsense.switching import SwitchOperation, change_position


@pytest.fixture(scope="module")
def engine():
    return ElectricalEngine()


def view_at(engine, device=None):
    state, _ = start_episode(EpisodeConfig(), engine)
    view = planning_view(controller_view(state))
    if device:
        changed = change_position(
            view.state, SwitchOperation(equipment=device, closed=False), engine.network
        )
        view = view.model_copy(update={"state": changed})
    return view


@pytest.mark.parametrize("device", [None, "line:feed_a", "transformer:tx_b2", "source:source"])
def test_reused_predictions_match_full_demand_native_reference(engine, device):
    view = view_at(engine, device)
    reference = FullDemandPredictor(view, "guarded", 100, engine)
    reused = Predictor(view, "guarded", 100, engine)
    before = deepcopy(engine.network)
    nominal = None
    for index, demand in enumerate(demand_samples(view, "guarded")):
        expected = reference._solve(view.state, demand)
        actual = reused._solve(view.state, demand)
        assert not _differences(actual, expected)
        assert actual["requested_kw"] == pytest.approx(sum(demand.values()), abs=1e-9)
        if index == 0:
            nominal = actual
    assert nominal["requested_kw"] == pytest.approx(sum(view.demand_kw.values()), abs=1e-9)
    assert engine.network == before
    if device:
        assert reused.solves < reference.solves
    else:
        assert reused.solves == reference.solves == 15


def test_disconnected_demand_is_counted_and_does_not_mutate_cached_outputs(engine, monkeypatch):
    view = view_at(engine, "line:feed_a")
    calls = []
    native = engine.solve

    def counted(state):
        calls.append(state)
        return native(state)

    monkeypatch.setattr(engine, "solve", counted)
    predictor = Predictor(view, "guarded", 1, engine)
    first = predictor._solve(view.state, view.demand_kw)
    changed = {**view.demand_kw, "a1": view.demand_kw["a1"] * 1.8}
    second = predictor._solve(view.state, changed)
    assert len(calls) == predictor.solves == 1 and predictor.cache_hits == 1
    assert second["requested_kw"] - first["requested_kw"] == pytest.approx(
        view.demand_kw["a1"] * 0.8, abs=1e-9
    )
    assert second["served_kw"] == first["served_kw"]
    assert first["requested_kw"] == pytest.approx(sum(view.demand_kw.values()), abs=1e-9)
    assert first is not second


@pytest.mark.parametrize("change", ["reconnect", "connected demand", "feeder factor"])
def test_a_changed_native_problem_cannot_use_a_disconnected_cache_hit(engine, change):
    view = view_at(engine, "line:feed_a")
    predictor = Predictor(view, "guarded", 1, engine)
    predictor._solve(view.state, view.demand_kw)
    state, demand = view.state, dict(view.demand_kw)
    if change == "reconnect":
        state = change_position(
            state, SwitchOperation(equipment="line:feed_a", closed=True), engine.network
        )
    elif change == "connected demand":
        demand["b1"] *= 1.2
    else:
        state = state.model_copy(update={"load_factors": {"a": 1, "b": 1.2, "c": 1}})
    with pytest.raises(BudgetExhausted):
        predictor._solve(state, demand)


def test_reconnection_checks_the_current_demand_and_detects_a_native_overload(engine):
    view = view_at(engine, "transformer:tx_b2")
    predictor = Predictor(view, "guarded", 10, engine)
    demand = {**view.demand_kw, "b2": 2000}
    disconnected = predictor._solve(view.state, demand)
    state = change_position(
        view.state, SwitchOperation(equipment="transformer:tx_b2", closed=True), engine.network
    )
    connected = predictor._solve(state, demand)
    assert disconnected["feasible"] and not connected["feasible"]
    assert predictor.solves == 2
    assert any(v["kind"] == "transformer_loading" for v in connected["violations"])


def test_reused_failure_retains_unknown_service_and_demand(engine, monkeypatch):
    view = view_at(engine, "line:feed_a")

    def fail(state):
        raise InvalidSwitching("native input rejected")

    monkeypatch.setattr(engine, "solve", fail)
    predictor = Predictor(view, "guarded", 1, engine)
    first = predictor._solve(view.state, view.demand_kw)
    second = predictor._solve(view.state, {**view.demand_kw, "a1": 700})
    assert not first["feasible"] and not second["feasible"]
    assert second["served_kw"] is second["requested_kw"] is None
    assert predictor.solves == 1 and predictor.cache_hits == 1


@pytest.mark.parametrize("damage", ["missing case", "native count", "disconnected demand"])
def test_study_checker_rejects_resigned_incomplete_or_miscounted_evidence(
    tmp_path, monkeypatch, damage
):
    root = Path(__file__).resolve().parents[2]
    monkeypatch.syspath_prepend(str(root / "experiments"))
    from run_native_reuse import verify

    report = json.loads((root / "experiments/native_reuse_results/results.json").read_text())
    if damage == "missing case":
        report["probes"].pop()
    elif damage == "native count":
        report["rows"][0]["reused"]["counted_adapter_calls"] += 1
    else:
        outcome = next(r for r in report["probes"] if r["case"] == "source-open")["outcomes"][0]
        for name in ("full_demand", "reused"):
            outcome[name]["requested_kw"] = 0
    report["content_sha256"] = canonical_hash(
        {k: v for k, v in report.items() if k != "content_sha256"}
    )
    (tmp_path / "results.json").write_text(json.dumps(report))
    with pytest.raises(ValueError):
        verify(tmp_path)
