from copy import deepcopy

import pytest

from gridsense.control import ControlSettings, ControlState, update_control
from gridsense.electrical import ElectricalEngine
from gridsense.episode_metrics import EpisodeMetrics, integrate_interval
from gridsense.episodes import (
    ActuatorEvent,
    DemandEvent,
    EpisodeConfig,
    EpisodeState,
    OutageEvent,
    RepairEvent,
    TransportEvent,
    advance_episode,
    controller_view,
    start_episode,
)
from gridsense.restoration import Predictor, demand_samples, dense_samples, plan, planning_view
from gridsense.restoration_reference import enumerate_plans
from gridsense.session_store import CreateSession, SessionMutation, SessionStore, replay_episode
from gridsense.switching import Command, PositionFeedback, SwitchOperation, confirm_commands


@pytest.fixture(scope="module")
def engine():
    return ElectricalEngine()


def outage(at=1, equipment="feed_a", kind="line", incident="trip"):
    return OutageEvent(at_s=at, incident_id=incident, equipment_kind=kind, equipment=equipment)


def run(engine, *, policy="nominal", events=None, horizon=9, **settings):
    config = EpisodeConfig(
        horizon_s=horizon,
        control=ControlSettings(policy=policy, **settings),
        events=tuple(
            events if events is not None else (outage(), RepairEvent(at_s=5, incident_id="trip"))
        ),
    )
    state, frame = start_episode(config, engine)
    frames = [frame]
    for _ in range(horizon):
        state, frame = advance_episode(state, engine)
        frames.append(frame)
    return state, frames


def test_native_restoration_then_break_before_make_recovery(engine):
    state, frames = run(engine)
    commands = list(state.control.commands.values())
    assert [c.operation.key for c in commands] == [
        "line:tie_c:close",
        "line:tie_c:open",
        "line:feed_a:close",
    ]
    assert all(c.status == "confirmed" and c.measured_at_s > c.issued_at_s for c in commands)
    assert frames[1]["electrical"]["unserved_kw"] == pytest.approx(1000, abs=0.001)
    assert frames[2]["control"]["supply_status"] == "alternate_supply_verified"
    assert frames[5]["physical"]["equipment_outages"] == []
    assert "feed_a" not in frames[5]["physical"]["closed_lines"]
    assert frames[6]["electrical"]["unserved_kw"] == pytest.approx(1000, abs=0.001)
    assert frames[7]["control"]["supply_status"] == "normal_supply_verified"
    assert state.metrics.unserved_kwh == pytest.approx(2000 / 3600, abs=1e-6)
    assert state.metrics.known_seconds == 9 and state.metrics.unknown_seconds == 0
    assert state.metrics.position_changes == 3 and state.metrics.first_recovery_delay_s == 1


def test_guarded_plan_can_preserve_critical_supply_at_a_service_cost(engine):
    state, frames = run(engine, policy="guarded")
    assert frames[3]["electrical"]["critical_served_kw"] == pytest.approx(400, abs=0.001)
    assert frames[3]["electrical"]["unserved_kw"] == pytest.approx(250, abs=0.001)
    assert frames[3]["physical"]["open_transformers"] == ["tx_b2"]
    assert all(f["electrical"]["feasible"] for f in frames)
    assert state.control.supply_status == "normal_supply_verified"
    assert state.metrics.position_changes == 5
    assert len(frames[1]["control"]["last_plan"]["uncertainty_samples"]) == 15


@pytest.mark.parametrize(
    "equipment,kind,missing",
    [("tx_a1", "transformer", 400), ("main", "transformer", 2550), ("source", "source", 2550)],
)
def test_unavailable_transformer_or_source_requires_repair_before_closing(
    engine, equipment, kind, missing
):
    state, frames = run(
        engine,
        events=(outage(equipment=equipment, kind=kind), RepairEvent(at_s=3, incident_id="trip")),
        horizon=5,
    )
    assert not frames[1]["control"]["commands"]
    assert frames[2]["electrical"]["unserved_kw"] == pytest.approx(missing, abs=0.001)
    assert len(state.control.commands) == 1
    command = next(iter(state.control.commands.values()))
    assert command.operation.equipment == kind + ":" + equipment and command.issued_at_s == 3
    assert state.last_electrical["unserved_kw"] < 0.001


def test_failed_actuators_are_bounded_and_never_confirmed_as_success(engine):
    state, frames = run(
        engine,
        horizon=8,
        events=(
            outage(),
            *(
                ActuatorEvent(at_s=1, equipment="line:" + tie, fail=True)
                for tie in ("tie_b", "tie_c")
            ),
        ),
    )
    commands = list(state.control.commands.values())
    assert len(commands) == 4 and all(c.status == "failed" for c in commands)
    assert state.metrics.actuation_attempts == 4 and state.metrics.position_changes == 0
    assert all(f["electrical"]["unserved_kw"] > 999 for f in frames[1:])
    assert state.control.supply_status == "partial_supply_verified"


def test_lost_feedback_blocks_recovery_even_if_electrical_supply_is_seen(engine):
    state, frames = run(
        engine,
        confirmation_timeout_s=2,
        events=(
            outage(),
            ActuatorEvent(at_s=1, equipment="line:tie_c", drop_feedback=True),
            RepairEvent(at_s=5, incident_id="trip"),
        ),
    )
    assert len(state.control.commands) == 1
    assert next(iter(state.control.commands.values())).status == "unknown"
    assert frames[3]["control"]["status"] == "confirmation_unknown"
    assert frames[3]["control"]["supply_status"] == "alternate_supply_verified"
    assert "feed_a" not in state.physical.closed_lines and "tie_c" in state.physical.closed_lines


@pytest.mark.parametrize("delay,status", [(1, "confirmed"), (3, "confirmed_late")])
def test_feedback_at_deadline_wins_and_late_feedback_resolves_unknown(engine, delay, status):
    state, frames = run(
        engine,
        horizon=6,
        confirmation_timeout_s=2,
        events=(
            outage(),
            ActuatorEvent(at_s=1, equipment="line:tie_c", feedback_delay_s=delay, duplicates=2),
        ),
    )
    assert state.control.commands["command-1"].status == status
    if delay == 3:
        assert frames[3]["control"]["status"] == "confirmation_unknown"
    deliveries = [
        e for f in frames for e in f["confirmation_events"] if e["kind"] == "position_feedback"
    ]
    assert sum(d["accepted"] for d in deliveries) == 1
    assert any(not d["accepted"] for d in deliveries)


def test_delayed_actuation_remains_unknown_until_actual_position_feedback(engine):
    state, frames = run(
        engine,
        horizon=7,
        confirmation_timeout_s=2,
        events=(outage(), ActuatorEvent(at_s=1, equipment="line:tie_c", actuation_delay_s=4)),
    )
    assert frames[3]["control"]["status"] == "confirmation_unknown"
    assert frames[4]["electrical"]["unserved_kw"] > 999
    assert frames[5]["electrical"]["unserved_kw"] < 0.001
    assert state.control.commands["command-1"].status == "confirmed_late"


def test_feedback_cannot_settle_the_wrong_command_or_use_an_old_measurement():
    command = Command(
        id="c",
        plan_id="p",
        operation=SwitchOperation(equipment="line:tie_b", closed=True),
        issued_at_s=4,
        deadline_s=6,
    )
    good = PositionFeedback(
        command_id="c", sequence=1, equipment="line:tie_b", closed=True, measured_at_s=5, due_s=6
    )
    bad = (
        good.model_copy(update={"command_id": "another"}),
        good.model_copy(update={"equipment": "line:tie_c"}),
        good.model_copy(update={"measured_at_s": 4}),
    )
    commands, pending, audit = confirm_commands({"c": command}, (*bad, good, good), 6)
    assert commands["c"].status == "confirmed" and not pending
    assert [r["accepted"] for r in audit] == [False, False, False, True, False]


def test_refault_during_recovery_blocks_closing_unavailable_equipment(engine):
    state, frames = run(
        engine,
        events=(outage(), RepairEvent(at_s=5, incident_id="trip"), outage(7, incident="again")),
    )
    attempt = frames[7]["actuation_events"][0]
    assert "unavailable" in attempt["reason"] and not attempt["closed"]
    assert state.control.commands["command-3"].status == "failed"
    assert "feed_a" not in state.physical.closed_lines
    assert [o.incident_id for o in state.physical.equipment_outages] == ["again"]


def test_repair_does_not_bypass_another_incident_on_the_same_equipment(engine):
    state, frames = run(
        engine,
        horizon=5,
        events=(
            outage(equipment="tx_a1", kind="transformer"),
            outage(1, "tx_a1", "transformer", "second"),
            RepairEvent(at_s=3, incident_id="trip"),
        ),
    )
    assert not state.control.commands
    assert all(f["electrical"]["unserved_kw"] > 399 for f in frames[1:])


def test_stale_load_can_cause_a_real_violation_and_received_alarms_drive_response(engine):
    state, frames = run(
        engine,
        horizon=8,
        events=(
            outage(),
            DemandEvent(at_s=1, feeder="c", factor=2),
            TransportEvent(at_s=1, equipment="load:c1", latency_s=0, drop=True),
            TransportEvent(at_s=1, equipment="load:c2", latency_s=0, drop=True),
        ),
    )
    assert frames[1]["control"]["last_plan"]["selected"]["prediction"]["feasible"]
    assert frames[2]["actuation_events"][0]["changed"]
    assert not frames[2]["electrical"]["feasible"]
    assert state.metrics.violation_ticks > 0
    assert any(
        a["kind"] == "raised" and a["alarm"]["rule"] in {"overload", "low_voltage"}
        for f in frames
        for a in f["alarm_changes"]
    )
    assert len(state.control.commands) > 1
    assert any(f["control"]["unsafe_positions"] for f in frames)


def test_planning_depends_on_the_received_projection_not_hidden_factors(engine):
    state, _ = start_episode(EpisodeConfig(events=(outage(),)), engine)
    state, _ = advance_episode(state, engine)
    hidden = state.model_copy(
        update={
            "physical": state.physical.model_copy(
                update={"load_factors": {"a": 2, "b": 2, "c": 2}}
            ),
            "future": (),
        }
    )
    assert controller_view(state) == controller_view(hidden)
    first, second = (planning_view(controller_view(s)) for s in (state, hidden))
    assert plan(first, "nominal", engine=engine) == plan(second, "nominal", engine=engine)
    before = deepcopy(engine.network)
    Predictor(first, "guarded", 100, engine).evaluate(first.state)
    assert engine.network == before


def test_missing_or_inconsistent_device_rows_refuse_planning(engine):
    state, _ = start_episode(EpisodeConfig(), engine)
    observation = controller_view(state)
    observation["signals"] = [
        r for r in observation["signals"] if r["sensor_id"] != "line:tie_b/closed"
    ]
    with pytest.raises(ValueError, match="Fresh availability"):
        planning_view(observation)
    control, command, _ = update_control(
        ControlState(), ControlSettings(policy="nominal"), observation, engine
    )
    assert command is None and control.status == "insufficient_information"


@pytest.mark.parametrize("policy", ["nominal", "guarded"])
def test_independent_sequence_enumerator_agrees_on_a_restoration_choice(engine, policy):
    state, _ = start_episode(EpisodeConfig(events=(outage(),)), engine)
    state, _ = advance_episode(state, engine)
    view = planning_view(controller_view(state))
    production = plan(view, policy, engine=engine)
    reference = enumerate_plans(view, policy, engine=engine)
    assert not production["budget_exhausted"] and reference["feasible_choice"]
    assert production["selected"]["operations"] == reference["operations"]
    assert production["selected"]["prediction"] == reference["prediction"]
    assert reference["sequences_tried"] > len(production["candidates"])


def test_solve_budget_exhaustion_is_explicit_and_cannot_claim_an_unchecked_choice(engine):
    state, _ = start_episode(EpisodeConfig(), engine)
    view = planning_view(controller_view(state))
    result = plan(view, "guarded", budget=1, engine=engine)
    assert result["native_evaluations"] == 1 and result["budget_exhausted"]
    assert not result["feasible_choice"] and result["selected"] is None
    assert len(demand_samples(view, "guarded")) == 15 and len(dense_samples(view)) == 729


def test_unknown_interval_is_neither_free_service_nor_known_unserved_energy():
    result = integrate_interval(EpisodeMetrics(), None)
    assert result.unknown_seconds == 1 and result.known_seconds == 0
    assert result.served_kwh == result.unserved_kwh == result.requested_kwh == 0


def test_pending_commands_survive_restart_and_retry_without_duplicate_actuation(tmp_path, engine):
    store = SessionStore(tmp_path / "control.sqlite3", engine=engine)
    config = EpisodeConfig(
        horizon_s=3, control=ControlSettings(policy="nominal"), events=(outage(),)
    )
    receipt = store.create(CreateSession(request_id="create", config=config))
    request = SessionMutation(request_id="first", expected_revision=0, operation="step")
    receipt = store.mutate(receipt["id"], request)
    assert store.read(receipt["id"])["control"]["commands"]["command-1"]["status"] == "pending"
    restarted = SessionStore(store.path, engine=engine)
    assert restarted.mutate(receipt["id"], request) == receipt
    restarted.restart_paused()
    for i in (1, 2):
        receipt = restarted.mutate(
            receipt["id"],
            SessionMutation(
                request_id="next-" + str(i), expected_revision=receipt["revision"], operation="step"
            ),
        )
    export = restarted.export(receipt["id"])
    assert export["final"]["checkpoint"]["metrics"]["actuation_attempts"] == 1
    assert replay_episode(export)["matched"]
    assert (
        EpisodeState.model_validate(export["final"]["checkpoint"])
        .control.commands["command-1"]
        .status
        == "confirmed"
    )


def test_new_donor_demand_invalidates_the_remaining_sequence(engine):
    state, frames = run(
        engine,
        policy="guarded",
        horizon=4,
        events=(outage(), DemandEvent(at_s=2, feeder="b", factor=2)),
    )
    checks = [e for e in frames[2]["control_events"] if e["kind"] == "sequence_revalidation"]
    assert checks and not checks[0]["feasible"]
    assert not any(c.operation.key == "line:tie_b:close" for c in state.control.commands.values())
    for previous, frame in zip(frames, frames[1:]):
        assert (
            frame["control"]["native_evaluations"] - previous["control"]["native_evaluations"]
            <= 2048
        )


def test_normal_recovery_refuses_an_overloaded_terminal_configuration(engine):
    state, _ = start_episode(EpisodeConfig(events=(outage(),)), engine)
    state, _ = advance_episode(state, engine)
    view = planning_view(controller_view(state))
    # A partly supplied alternate topology with an excessive held A2 estimate.
    changed = view.state.model_copy(
        update={
            "equipment_outages": (),
            "closed_lines": ("feed_b", "seg_b", "feed_c", "seg_c", "tie_c"),
        }
    )
    view = view.model_copy(update={"state": changed, "demand_kw": {**view.demand_kw, "a2": 1200}})
    result = plan(view, "nominal", engine=engine, goal="normal")
    reference = enumerate_plans(view, "nominal", engine=engine, goal="normal")
    assert result["selected"]["operations"] == [] and not result["feasible_choice"]
    assert not reference["feasible_choice"]
    assert result["selected"]["prediction"]["feasible"]


def test_received_overload_takes_priority_over_return_to_normal(engine):
    state, frames = run(
        engine,
        policy="guarded",
        horizon=12,
        events=(
            outage(),
            RepairEvent(at_s=5, incident_id="trip"),
            DemandEvent(at_s=6, feeder="a", factor=2),
        ),
    )
    assert not frames[7]["electrical"]["feasible"]
    assert frames[7]["control"]["last_plan"]["goal"] == "restore"
    assert frames[7]["control"]["last_plan"]["feasible_choice"]
    assert all(f["electrical"]["feasible"] for f in frames[8:])
    assert state.metrics.violation_ticks == 1
    assert state.last_electrical["unserved_kw"] > 1999
    assert state.control.supply_status == "partial_supply_verified"


def test_late_position_telemetry_blocks_the_next_command_until_it_catches_up(engine):
    state, frames = run(
        engine,
        horizon=9,
        events=(
            outage(),
            RepairEvent(at_s=5, incident_id="trip"),
            TransportEvent(at_s=6, equipment="line:tie_c", latency_s=2),
        ),
    )
    assert frames[6]["control"]["status"] == "insufficient_information"
    assert frames[7]["control"]["status"] == "insufficient_information"
    closing = next(
        c for c in state.control.commands.values() if c.operation.key == "line:feed_a:close"
    )
    assert closing.issued_at_s == 8 and closing.status == "confirmed"


def test_recovery_does_not_open_backup_when_only_one_command_remains(engine):
    state, frames = run(engine, max_commands=2, horizon=16)
    assert len(state.control.commands) == 1
    assert all(f["electrical"]["unserved_kw"] < 0.1 for f in frames[2:])
    assert state.control.supply_status == "alternate_supply_verified"
    assert "feed_a" not in state.physical.closed_lines
    assert not state.physical.equipment_outages  # Repaired, still supplied through the tie.
    assert state.metrics.unserved_kwh == pytest.approx(1000 / 3600, abs=1e-6)


def test_plans_fit_the_remaining_command_allowance(engine):
    for cap in (1, 2, 3):
        _, frames = run(engine, policy="guarded", max_commands=cap)
        for frame in frames:
            control = frame["control"]
            assert len(control["commands"]) + len(control["remaining"]) <= cap


def test_command_and_decision_caps_stop_new_work_explicitly(engine):
    state, _ = run(engine, horizon=6, max_commands=1)
    assert len(state.control.commands) == 1
    state, frames = run(engine, horizon=6, max_decisions=1)
    assert state.control.decision_count == 1
    assert frames[5]["control"]["status"] == "decision_limit"


@pytest.mark.parametrize(
    "event",
    [
        {"kind": "actuator", "at_s": 1, "equipment": "load:a1"},
        {"kind": "actuator", "at_s": 1, "equipment": "line:tie_b", "actuation_delay_s": 0},
        {"kind": "actuator", "at_s": 1, "equipment": "line:tie_b", "feedback_delay_s": 31},
    ],
)
def test_actuator_scenarios_reject_unknown_devices_and_invalid_timing(event):
    with pytest.raises(ValueError):
        EpisodeConfig(events=(event,))


def test_controlled_playback_is_identical_at_all_supported_rates(tmp_path, engine):
    store = SessionStore(tmp_path / "rates.sqlite3", engine=engine)
    frames = []
    for rate in (1, 5, 10):
        config = EpisodeConfig(
            horizon_s=3, control=ControlSettings(policy="nominal"), events=(outage(),)
        )
        receipt = store.create(CreateSession(request_id="rate-" + str(rate), config=config))
        receipt = store.mutate(
            receipt["id"],
            SessionMutation(request_id="play", expected_revision=0, operation="play", rate=rate),
        )
        for _ in range(3):
            receipt = store.system_action(receipt["id"], receipt["revision"], "auto_tick")
        export = store.export(receipt["id"])
        assert replay_episode(export)["matched"]
        frames.append(export["frames"])
    assert frames[0] == frames[1] == frames[2]


def test_command_issue_rolls_back_with_a_failed_transaction(tmp_path, engine):
    import sqlite3

    store = SessionStore(tmp_path / "rollback.sqlite3", engine=engine)
    receipt = store.create(
        CreateSession(
            request_id="create",
            config=EpisodeConfig(control=ControlSettings(policy="nominal"), events=(outage(),)),
        )
    )
    before = store.export(receipt["id"])
    with store.connect(write=True) as db:
        db.execute(
            "CREATE TRIGGER fail_write BEFORE INSERT ON live_actions BEGIN SELECT RAISE(ABORT, 'write failed'); END"
        )
    request = SessionMutation(request_id="step", expected_revision=0, operation="step")
    with pytest.raises(sqlite3.IntegrityError):
        store.mutate(receipt["id"], request)
    assert store.export(receipt["id"]) == before
    with store.connect(write=True) as db:
        db.execute("DROP TRIGGER fail_write")
    store.mutate(receipt["id"], request)
    after = store.export(receipt["id"])
    assert len(after["final"]["checkpoint"]["control"]["commands"]) == 1
    assert len(after["final"]["checkpoint"]["actuations"]) == 1
