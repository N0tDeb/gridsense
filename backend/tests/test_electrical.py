import pytest
from gridsense.domain import Action, Operation
from gridsense.electrical import ElectricalEngine, InvalidSwitching
from gridsense.network import initial_state


def close(line):
    return Action(id=line, label=line, operations=(Operation(line=line, closed=True),))


def test_switching_changes_actual_dss_voltage_and_served_power():
    engine = ElectricalEngine(restoration_baseline_kw={"a1": 0, "a2": 0})
    state = initial_state({"a": 1, "b": 0.7, "c": 0.9})
    before = engine.solve(state)
    after = engine.execute(state, close("tie_b"))
    assert before.converged and after.result.converged
    assert before.restored_kw == 0
    assert after.result.restored_kw == pytest.approx(1000, abs=0.1)
    engine.ctx.Circuit.SetActiveBus("a1_lv")
    assert min(engine.ctx.Bus.puVmagAngle()[::2]) > 0.95
    engine.ctx.Circuit.SetActiveElement("Line.feed_a")
    assert engine.ctx.CktElement.IsOpen(1, 1) and engine.ctx.CktElement.IsOpen(2, 1)
    engine.ctx.Circuit.SetActiveElement("Line.tie_b")
    assert not engine.ctx.CktElement.IsOpen(1, 1)
    assert state.closed_lines != after.final_state.closed_lines


def test_reachability_does_not_make_an_overloaded_route_feasible():
    outcome = ElectricalEngine(restoration_baseline_kw={"a1": 0, "a2": 0}).execute(
        initial_state({"a": 1, "b": 1.5, "c": 0.9}), close("tie_b")
    )
    assert outcome.result.restored_kw == pytest.approx(1000, abs=0.1)
    assert not outcome.result.feasible
    assert any(
        v.kind == "line_loading" and v.element == "feed_b" for v in outcome.result.violations
    )


def test_alternative_donor_avoids_that_violation():
    result = (
        ElectricalEngine(restoration_baseline_kw={"a1": 0, "a2": 0})
        .execute(initial_state({"a": 1, "b": 1.5, "c": 0.9}), close("tie_c"))
        .result
    )
    assert result.feasible
    assert result.restored_kw == pytest.approx(1000, abs=0.1)


def test_partial_restoration_keeps_critical_load_and_accounts_for_unserved_demand():
    state = initial_state({"a": 1, "b": 1.65, "c": 1.6})
    action = Action(
        id="partial",
        label="partial",
        operations=(Operation(line="seg_a", closed=False), Operation(line="tie_b", closed=True)),
    )
    outcome = ElectricalEngine().execute(state, action)
    assert len(outcome.steps) == 2
    assert all(s.feasible for s in outcome.steps)
    assert outcome.result.critical_served_kw == pytest.approx(400, abs=0.1)
    assert outcome.result.unserved_kw == pytest.approx(600, abs=0.1)


@pytest.mark.parametrize("line", ["feed_a", "unknown"])
def test_invalid_switching_is_rejected(line):
    with pytest.raises(InvalidSwitching):
        ElectricalEngine().execute(initial_state({"a": 1, "b": 1, "c": 1}), close(line))


def test_two_ties_cannot_create_a_loop():
    action = Action(
        id="loop",
        label="loop",
        operations=(Operation(line="tie_b", closed=True), Operation(line="tie_c", closed=True)),
    )
    with pytest.raises(InvalidSwitching, match="radial"):
        ElectricalEngine().execute(initial_state({"a": 1, "b": 1, "c": 1}), action)


def test_native_contexts_do_not_contaminate_each_other():
    one, two = ElectricalEngine(), ElectricalEngine()
    state = initial_state({"a": 1, "b": 0.7, "c": 0.9})
    first = one.execute(state, close("tie_b")).result
    two.solve(initial_state({"a": 1.4, "b": 1.9, "c": 1.7}))
    one.ctx.Circuit.SetActiveBus("a1_lv")
    assert min(one.ctx.Bus.puVmagAngle()[::2]) == pytest.approx(first.voltages_pu["a1_lv"])


def test_nonconvergence_cannot_be_marked_feasible(monkeypatch):
    engine = ElectricalEngine()
    monkeypatch.setattr(type(engine.ctx.Solution), "Converged", lambda self: False)
    result = engine.solve(initial_state({"a": 1, "b": 1, "c": 1}))
    assert not result.feasible
    assert any(v.kind == "solver" for v in result.violations)


def test_winding_limit_is_enforced_independently_of_line_limits():
    engine = ElectricalEngine()
    engine.network["loads"][0]["kva"] = 250
    result = engine.execute(initial_state({"a": 1, "b": 0.7, "c": 0.9}), close("tie_b")).result
    assert any(v.kind == "transformer_loading" and v.element == "tx_a1" for v in result.violations)


def test_voltage_limit_is_electrical_and_enforced():
    engine = ElectricalEngine()
    engine.network["lines"][6]["length_km"] = 25
    result = engine.execute(initial_state({"a": 1, "b": 0.7, "c": 0.9}), close("tie_b")).result
    assert any(v.kind == "voltage" for v in result.violations)
