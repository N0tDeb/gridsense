"""Native checks for delay-aware decisions and transition service accounting."""

from copy import deepcopy

import pytest

from gridsense.control import ControlSettings, ControlState, update_control
from gridsense.electrical import ElectricalEngine
from gridsense.episodes import (
    ActuatorEvent,
    DemandEvent,
    EpisodeConfig,
    OutageEvent,
    RepairEvent,
    TransportEvent,
    advance_episode,
    controller_view,
    start_episode,
)
from gridsense.network import healthy_state
from gridsense.restoration import (
    PlanningTiming,
    Predictor,
    blocked_exposure,
    check_sequence,
    combined_prediction,
    energy_prediction,
    forecast_sequence,
    optimistic_rank,
    plan,
    planning_view,
    projected_view,
    rank,
    sequence_states,
    section_loads,
)
from gridsense.restoration_reference import enumerate_plans
from gridsense.switching import SwitchOperation, change_position, position_key
from gridsense.telemetry import (
    MeasurementPolicy,
    PendingSample,
    TelemetryState,
    deliver,
    estimate_demand,
    native_samples,
)


@pytest.fixture(scope="module")
def engine():
    return ElectricalEngine()


def tripped_view(engine, **settings):
    config = EpisodeConfig(
        events=(
            OutageEvent(at_s=1, incident_id="trip", equipment_kind="line", equipment="feed_a"),
        ),
        **settings,
    )
    state, _ = start_episode(config, engine)
    state, _ = advance_episode(state, engine)
    return state, planning_view(controller_view(state))


def test_projection_ages_received_bounds_and_preserves_their_mean(engine):
    _, view = tripped_view(engine)
    future = projected_view(view, 5)
    assert future.demand_kw == view.demand_kw and future.at_s == view.at_s + 5
    for key, mean in view.demand_kw.items():
        assert future.bounds_kw[key][0] == pytest.approx(view.bounds_kw[key][0] - mean * 0.1)
        assert future.bounds_kw[key][1] == pytest.approx(view.bounds_kw[key][1] + mean * 0.1)
    assert view.evidence == future.evidence


def test_projection_caps_growth_without_narrowing_already_wider_evidence(engine):
    _, view = tripped_view(engine)
    view = view.model_copy(update={"maximum_uncertainty_pct": 20})
    future = projected_view(view, 100)
    for key, mean in view.demand_kw.items():
        assert future.bounds_kw[key] == pytest.approx((mean * 0.8, mean * 1.2))
    wider = view.model_copy(
        update={
            "bounds_kw": {key: (mean * 0.5, mean * 1.5) for key, mean in view.demand_kw.items()}
        }
    )
    assert projected_view(wider, 100).bounds_kw == wider.bounds_kw


def test_future_arrival_can_fail_a_native_check_that_passes_now(engine):
    _, view = tripped_view(
        engine,
        initial_factors={"a": 0.8, "b": 1.45, "c": 1.25},
        measurements=MeasurementPolicy(initial_uncertainty_pct=0),
    )
    operation = SwitchOperation(equipment="line:tie_c", closed=True)
    state = sequence_states(view, (operation,), engine.network)[-1]
    predictor = Predictor(view, "guarded", 200, engine)
    assert predictor.evaluate(state, 0)["feasible"]
    delayed = check_sequence(
        view, (operation,), "guarded", engine=engine, timing=PlanningTiming(actuation_delay_s=5)
    )
    assert not delayed["feasible"] and delayed["steps"][0]["offset_s"] == 5
    assert delayed["steps"][0]["prediction"]["violations"]


def test_confirmation_wait_is_checked_before_the_next_operation(engine):
    _, view = tripped_view(engine)
    operations = (
        SwitchOperation(equipment="line:seg_a", closed=False),
        SwitchOperation(equipment="line:tie_b", closed=True),
    )
    timing = PlanningTiming(actuation_delay_s=2, confirmation_delay_s=1)
    result = check_sequence(view, operations, "nominal", engine=engine, timing=timing)
    assert result["feasible"]
    assert [s["offset_s"] for s in result["steps"]] == [2, 4, 5, 6]
    assert result["completion_offset_s"] == 6


@pytest.mark.parametrize("growth,expected_solves", [(0, 15), (2, 29)])
def test_cache_reuses_native_problems_without_reusing_changed_guard_bounds(
    engine, monkeypatch, growth, expected_solves
):
    state, _ = start_episode(EpisodeConfig(), engine)
    view = planning_view(controller_view(state)).model_copy(update={"growth_pct_per_s": growth})
    calls = []
    before = deepcopy(engine.network)
    native = engine.solve

    def measured(model):
        calls.append(deepcopy(engine.network))
        return native(model)

    monkeypatch.setattr(engine, "solve", measured)
    predictor = Predictor(view, "guarded", expected_solves, engine)
    first = predictor.evaluate(view.state, 0)
    later = predictor.evaluate(view.state, 1)
    assert first["feasible"] and later["feasible"]
    assert predictor.solves == len(calls) == expected_solves
    assert first["nominal"] == later["nominal"]
    assert (first["projected_bounds_kw"] == later["projected_bounds_kw"]) is (growth == 0)
    assert engine.network == before


def test_ordered_paths_with_the_same_final_topology_have_different_native_service_loss(engine):
    _, view = tripped_view(engine)
    shedding = SwitchOperation(equipment="line:feed_c", closed=False)
    section = SwitchOperation(equipment="line:seg_a", closed=False)
    restore = SwitchOperation(equipment="line:tie_b", closed=True)
    timing = PlanningTiming()
    predictor = Predictor(view, "nominal", 100, engine)
    candidates = []
    for operations in ((shedding, section, restore), (section, shedding, restore)):
        states = sequence_states(view, operations, engine.network)
        checked = forecast_sequence(predictor, operations, timing, states=states)
        assert checked["feasible"]
        candidates.append(
            {
                "operations": [o.model_dump(mode="json") for o in operations],
                "prediction": combined_prediction(checked, predictor.nominal(states[-1])),
                "energy": energy_prediction(predictor, states, timing),
            }
        )
        assert optimistic_rank(view, operations, states, timing, engine.network) <= rank(
            candidates[-1]
        )
    early, late = candidates
    assert early["prediction"]["nominal"] == late["prediction"]["nominal"]
    assert early["energy"]["critical_unserved_kwh"] == pytest.approx(
        late["energy"]["critical_unserved_kwh"], abs=1e-7
    )
    assert early["energy"]["unserved_kwh"] - late["energy"]["unserved_kwh"] == pytest.approx(
        850 / 3600, abs=1e-7
    )
    assert rank(late) < rank(early)


def test_return_to_normal_does_not_start_a_sequence_that_the_horizon_truncates(engine):
    config = EpisodeConfig(
        horizon_s=6,
        control=ControlSettings(policy="nominal"),
        events=(
            OutageEvent(at_s=1, incident_id="trip", equipment_kind="line", equipment="feed_a"),
            RepairEvent(at_s=5, incident_id="trip"),
        ),
    )
    state, _ = start_episode(config, engine)
    frames = []
    for _ in range(config.horizon_s):
        state, frame = advance_episode(state, engine)
        frames.append(frame)
    assert len(state.control.commands) == 1
    assert state.control.supply_status == "alternate_supply_verified"
    assert not state.physical.equipment_outages and "feed_a" not in state.physical.closed_lines
    assert all(f["electrical"]["unserved_kw"] < 0.001 for f in frames[1:])


def test_private_actuator_overrides_do_not_change_the_public_planning_model(engine):
    state, view = tripped_view(engine)
    hidden = state.model_copy(
        update={
            "actuators": {
                "line:tie_c": ActuatorEvent(
                    at_s=1,
                    equipment="line:tie_c",
                    actuation_delay_s=8,
                    feedback_delay_s=10,
                    fail=True,
                ),
            }
        }
    )
    assert controller_view(hidden) == controller_view(state)
    assert planning_view(controller_view(hidden)) == view
    assert plan(view, "nominal", engine=engine, max_operations=1) == plan(
        planning_view(controller_view(hidden)), "nominal", engine=engine, max_operations=1
    )


def test_public_timing_must_fit_the_confirmation_protocol():
    with pytest.raises(ValueError, match="fit the confirmation timeout"):
        ControlSettings(planning_timing=PlanningTiming(actuation_delay_s=4, confirmation_delay_s=2))
    settings = ControlSettings(
        confirmation_timeout_s=6,
        planning_timing=PlanningTiming(actuation_delay_s=4, confirmation_delay_s=2),
    )
    assert settings.planning_timing.step_s == 6


@pytest.mark.parametrize("policy", ["nominal", "guarded"])
def test_pruned_search_matches_separate_enumeration_with_timing_and_load_shedding(engine, policy):
    _, view = tripped_view(engine)
    timing = PlanningTiming(actuation_delay_s=2, confirmation_delay_s=1)
    production = plan(view, policy, engine=engine, max_operations=2, timing=timing)
    reference = enumerate_plans(view, policy, engine=engine, max_operations=2, timing=timing)
    assert not production["budget_exhausted"] and production["search_complete"]
    assert production["feasible_choice"] == reference["feasible_choice"]
    assert production["selected"]["operations"] == reference["operations"]
    assert production["selected"]["prediction"] == reference["prediction"]
    assert production["service_bound_pruned"] > 0
    assert production["native_evaluations"] < reference["native_evaluations"]


def test_shrinking_energy_window_reconsiders_a_hold_without_new_measurements(engine, monkeypatch):
    state, _ = tripped_view(engine)
    observation = controller_view(state)
    calls = []

    def hold(view, policy, **kwargs):
        result = plan(view, policy, **kwargs)
        result["feasible_choice"] = False
        calls.append(result)
        return result

    monkeypatch.setattr("gridsense.control.plan", hold)
    settings = ControlSettings(policy="nominal")
    control, command, _ = update_control(ControlState(), settings, observation, engine)
    assert command is None and len(calls) == 1
    same = deepcopy(observation)
    same["at_s"] += 2
    same["remaining_horizon_s"] = 10
    control, _, _ = update_control(control, settings, same, engine)
    assert len(calls) == 1
    shorter = deepcopy(same)
    shorter["at_s"] += 2
    shorter["remaining_horizon_s"] = 9
    _, _, _ = update_control(control, settings, shorter, engine)
    assert len(calls) == 2 and calls[-1]["energy_horizon_s"] == 9


def stale_east_config():
    return EpisodeConfig(
        horizon_s=12,
        control=ControlSettings(policy="nominal"),
        events=(
            OutageEvent(at_s=1, incident_id="trip", equipment_kind="line", equipment="feed_a"),
            DemandEvent(at_s=1, feeder="c", factor=2),
            TransportEvent(at_s=1, equipment="load:c1", latency_s=0, drop=True),
            TransportEvent(at_s=1, equipment="load:c2", latency_s=0, drop=True),
        ),
    )


def test_fresh_measured_overload_requires_a_relevant_first_switch_without_hidden_demand(engine):
    state, _ = start_episode(stale_east_config(), engine)
    frames = []
    for _ in range(12):
        state, frame = advance_episode(state, engine)
        frames.append(frame)
    proposal = frames[1]["control"]["last_plan"]
    view = planning_view(frames[1]["observation"])
    assert view.demand_kw["c1"] == pytest.approx(500, abs=0.001)
    assert view.demand_kw["c2"] == pytest.approx(350, abs=0.001)
    overload = next(r for r in view.measured_overloads if r["equipment"] == "line:feed_c")
    assert overload["row"]["value"] > 100 and overload["row"]["measured_at_s"] == 2
    unrelated = check_sequence(
        view, (SwitchOperation(equipment="line:seg_b", closed=False),), "nominal", engine=engine
    )
    assert not unrelated["feasible"] and "first switch" in unrelated["reason"]
    first = SwitchOperation.model_validate(proposal["selected"]["operations"][0])
    changed = change_position(view.state, first, engine.network)
    assert section_loads(changed, "line:feed_c", engine.network) < section_loads(
        view.state, "line:feed_c", engine.network
    )
    assert state.metrics.violation_ticks <= 3
    assert all(frame["electrical"]["feasible"] for frame in frames[4:])
    assert len(state.control.commands) <= 4


def test_known_overloaded_load_set_cannot_be_bypassed_by_an_unrelated_position(engine):
    state, _ = start_episode(stale_east_config(), engine)
    state, _ = advance_episode(state, engine)
    state, _ = advance_episode(state, engine)
    view = planning_view(controller_view(state)).model_copy(
        update={"measured_overloads": (), "unsafe_exposures": state.control.unsafe_exposures}
    )
    changed = change_position(
        view.state, SwitchOperation(equipment="line:seg_b", closed=False), engine.network
    )
    assert position_key(changed, engine.network) != position_key(view.state, engine.network)
    assert Predictor(view, "nominal", 10, engine).evaluate(changed)["feasible"]
    assert blocked_exposure(view, changed, engine.network)
    checked = check_sequence(
        view.model_copy(update={"state": changed}), (), "nominal", engine=engine
    )
    assert not checked["feasible"]


@pytest.mark.parametrize("changed_load,clears_memory", [("b1", False), ("c1", True)])
def test_exposure_memory_only_reopens_on_a_related_received_demand_change(
    engine, monkeypatch, changed_load, clears_memory
):
    state, _ = start_episode(stale_east_config(), engine)
    for _ in range(5):
        state, _ = advance_episode(state, engine)
    assert state.control.unsafe_exposures and state.control.pending_id is None
    observation = deepcopy(controller_view(state))
    for row in observation["demand_estimates"]:
        if row["load_id"] == changed_load:
            row["kw"] += 20

    def hold(view, policy, **kwargs):
        result = plan(view, policy, **kwargs)
        result["feasible_choice"] = False
        return result

    monkeypatch.setattr("gridsense.control.plan", hold)
    control, _, _ = update_control(state.control, state.config.control, observation, engine)
    assert bool(control.unsafe_exposures) is not clears_memory


def test_a_native_sag_within_the_load_model_window_still_updates_demand(engine):
    physical = healthy_state({"a": 3, "b": 3, "c": 3})
    result = engine.solve(physical)
    affected = [r for r in result.load_measurements if 0.8 <= r["voltage_pu"] < 0.95]
    assert result.converged and affected
    samples = native_samples(engine, physical, result, 0, 0)
    telemetry = TelemetryState(pending=tuple(PendingSample(due_s=0, row=r) for r in samples))
    telemetry, _, _ = deliver(telemetry, 0)
    estimated = estimate_demand(telemetry, engine.network, 0, MeasurementPolicy())
    for row in affected:
        assert estimated.estimates[row["load_id"]].kw == pytest.approx(row["native_kw"], abs=1e-7)
        assert estimated.estimates[row["load_id"]].measured_at_s == 0
