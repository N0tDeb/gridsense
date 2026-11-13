import pytest

from gridsense.cases import PortableCase
from gridsense.domain import Action, EquipmentOutage, Operation, Scenario
from gridsense.electrical import ElectricalEngine, InvalidSwitching
from gridsense.network import healthy_state, initial_state, isolate_outage, repair_outage
from gridsense.planning import candidate_actions, choose_action
from gridsense.plants import plant_for
from gridsense.service import observations


def outage(equipment, kind="transformer", incident_id="incident-1"):
    return EquipmentOutage(incident_id=incident_id, kind=kind, equipment=equipment)


def row(result, load):
    return next(r for r in result.load_measurements if r["load_id"] == load)


def test_healthy_start_preserves_the_separate_isolated_snapshot_contract():
    engine = ElectricalEngine()
    healthy = healthy_state()
    result = engine.solve(healthy)
    assert "feed_a" in healthy.closed_lines and not healthy.locked_open
    assert result.feasible and result.requested_kw == 2550
    assert result.served_kw == pytest.approx(2550, abs=0.001)
    assert result.voltage_compliant_served_kw == result.served_kw
    assert abs(result.balance_residual_kw) < 0.001
    assert abs(result.balance_residual_kvar) < 0.001
    assert all(r["energized"] and r["quality"] == "solved" for r in result.load_measurements)
    assert engine.solve(initial_state(healthy.load_factors)).unserved_kw == pytest.approx(
        1000, abs=0.001
    )


def test_failed_transformer_cannot_be_bypassed_by_an_mv_tie():
    engine = ElectricalEngine()
    state = isolate_outage(healthy_state({"a": 1, "b": 0.7, "c": 0.9}), outage("tx_a1"))
    action = Action(
        id="transfer",
        label="Transfer MV supply",
        operations=(Operation(line="feed_a", closed=False), Operation(line="tie_b", closed=True)),
    )
    result = engine.execute(state, action).result
    assert result.feasible and "a1" in result.energized_buses
    assert row(result, "a1")["served_kw"] == 0
    assert row(result, "a1")["native_kw"] == 0
    assert not row(result, "a1")["energized"]
    assert row(result, "a2")["served_kw"] == pytest.approx(600, abs=0.001)
    assert result.unserved_kw == pytest.approx(400, abs=0.001)
    engine.ctx.Circuit.SetActiveElement("Transformer.tx_a1")
    assert all(engine.ctx.CktElement.IsOpen(t, 1) for t in (1, 2))
    engine.ctx.Circuit.SetActiveBus("a1_lv")
    assert max(engine.ctx.Bus.puVmagAngle()[::2]) < 0.001


def test_repair_retains_isolation_and_does_not_clear_a_second_incident():
    engine = ElectricalEngine()
    state = isolate_outage(healthy_state(), outage("tx_a1", incident_id="one"))
    state = isolate_outage(state, outage("tx_a1", incident_id="two"))
    state = repair_outage(state, "one")
    assert [o.incident_id for o in state.equipment_outages] == ["two"]
    with pytest.raises(InvalidSwitching, match="Unavailable"):
        engine.solve(state.model_copy(update={"open_transformers": ()}))
    state = repair_outage(state, "two")
    assert not state.equipment_outages and "tx_a1" in state.open_transformers
    assert engine.solve(state).unserved_kw == pytest.approx(400, abs=0.001)
    reconnected = state.model_copy(update={"open_transformers": ()})
    assert engine.solve(reconnected).unserved_kw == pytest.approx(0, abs=0.001)


@pytest.mark.parametrize(
    "kind,equipment", [("line", "feed_a"), ("transformer", "main"), ("source", "source")]
)
def test_upstream_outage_repair_requires_explicit_reconnection(kind, equipment):
    engine = ElectricalEngine()
    state = isolate_outage(healthy_state(), outage(equipment, kind))
    result = engine.solve(state)
    assert result.converged and result.feasible
    expected = 1000 if kind == "line" else 2550
    assert result.unserved_kw == pytest.approx(expected, abs=0.001)
    assert abs(result.balance_residual_kw) < 0.001
    repaired = repair_outage(state, "incident-1")
    assert engine.solve(repaired).unserved_kw == pytest.approx(expected, abs=0.001)
    if kind == "line":
        assert all(a.id != "feed_a" for a in candidate_actions(state, engine.network))
        invalid = state.model_copy(update={"closed_lines": healthy_state().closed_lines})
        reconnected = repaired.model_copy(update={"closed_lines": healthy_state().closed_lines})
    elif kind == "transformer":
        invalid = state.model_copy(update={"open_transformers": ()})
        reconnected = repaired.model_copy(update={"open_transformers": ()})
    else:
        invalid = state.model_copy(update={"source_connected": True})
        reconnected = repaired.model_copy(update={"source_connected": True})
    with pytest.raises(InvalidSwitching, match="Unavailable"):
        engine.solve(invalid)
    assert engine.solve(reconnected).feasible
    assert engine.solve(reconnected).unserved_kw == pytest.approx(0, abs=0.001)


def test_separate_outages_keep_requested_demand_and_survive_round_trip():
    state = isolate_outage(healthy_state(), outage("tx_a1", incident_id="medical"))
    state = isolate_outage(state, outage("feed_c", "line", "east"))
    state = type(state).model_validate_json(state.model_dump_json())
    result = ElectricalEngine().solve(state)
    assert result.unserved_kw == pytest.approx(1250, abs=0.001)
    assert result.requested_kw == 2550
    assert result.served_kw + result.unserved_kw == pytest.approx(result.requested_kw)


@pytest.mark.parametrize("kind", ["line", "transformer", "source"])
def test_unknown_equipment_is_rejected(kind):
    with pytest.raises(ValueError, match="Unknown"):
        isolate_outage(healthy_state(), outage("invented", kind))


def test_duplicate_incidents_and_unknown_repairs_are_rejected():
    state = isolate_outage(healthy_state(), outage("tx_a1"))
    with pytest.raises(ValueError, match="unique"):
        isolate_outage(state, outage("tx_b1"))
    with pytest.raises(ValueError, match="Unknown"):
        repair_outage(state, "missing")


def test_observation_based_planning_keeps_disclosed_equipment_status():
    scenario = Scenario(load_b=0.7, reported_b=0.7, telemetry_age_s=0)
    engine = ElectricalEngine()
    state = isolate_outage(initial_state({"a": 1, "b": 0.7, "c": 0.9}), outage("tx_a1"))
    observed = observations(scenario, "2026-01-01T00:00:00+00:00", engine.network)
    decision = choose_action(observed, state, "nominal")
    assert all(c.nominal.critical_served_kw == 0 for c in decision.candidates)
    altered_truth = state.model_copy(update={"load_factors": {"a": 1.5, "b": 2, "c": 2}})
    assert choose_action(observed, altered_truth, "nominal") == decision


def test_native_power_is_not_capped_service_credit():
    engine = ElectricalEngine()
    # A stiff overvoltage source exercises the declared high-voltage impedance
    # fallback. The native load can consume more than the requested base demand.
    original = engine._commands
    engine._commands = lambda state: [*original(state), "Edit Vsource.source pu=1.3"]
    result = engine.solve(healthy_state())
    assert result.converged and not result.feasible
    assert result.native_load_kw > result.requested_kw
    assert result.served_kw <= result.requested_kw
    assert result.voltage_compliant_served_kw == 0
    assert abs(result.balance_residual_kw) < 0.001
    assert result.source_kw - result.served_kw - result.losses_kw > 1


def test_nonconvergence_invalidates_new_measurement_and_balance_fields(monkeypatch):
    engine = ElectricalEngine()
    monkeypatch.setattr(type(engine.ctx.Solution), "Converged", lambda self: False)
    result = engine.solve(healthy_state())
    assert not result.feasible
    assert (
        result.native_load_kw
        is result.balance_residual_kw
        is result.voltage_compliant_served_kw
        is None
    )
    assert all(
        r["quality"] == "unconverged" and r["native_kw"] is None for r in result.load_measurements
    )


def test_ieee_adapter_rejects_unimplemented_equipment_states():
    plant = plant_for(PortableCase(feeder="ieee13", fault="632670"))
    with pytest.raises(ValueError, match="teaching adapter only"):
        plant.solve(plant.truth.model_copy(update={"source_connected": False}))
