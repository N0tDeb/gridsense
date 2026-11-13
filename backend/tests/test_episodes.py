import pytest
from dss import DSSException
from gridsense.electrical import ElectricalEngine
from gridsense.episodes import (
    DemandEvent,
    EpisodeConfig,
    OutageEvent,
    RepairEvent,
    TransportEvent,
    advance_episode,
    controller_view,
    schedule,
    start_episode,
)
from gridsense.rules import RuleSettings, RuleState, update_rules
from gridsense.telemetry import (
    MeasurementPolicy,
    PendingSample,
    Signal,
    TelemetryState,
    deliver,
    estimate_demand,
)


@pytest.fixture(scope="module")
def engine():
    return ElectricalEngine()


def trip(at=1, incident="first", equipment="tx_a1"):
    return OutageEvent(
        at_s=at, incident_id=incident, equipment_kind="transformer", equipment=equipment
    )


def signal(sequence, value, *, measured=None, quality="valid", quantity="voltage_min_pu"):
    at = sequence if measured is None else measured
    return Signal(
        sequence=sequence,
        sensor_id="bus:a1_lv/" + quantity,
        equipment="bus:a1_lv",
        quantity=quantity,
        value=value,
        unit="pu",
        measured_at_s=at,
        received_at_s=at,
        quality=quality,
        source="OpenDSS",
    )


def test_native_episode_isolates_then_repairs_without_reconnecting(engine):
    config = EpisodeConfig(horizon_s=3, events=(trip(), RepairEvent(at_s=2, incident_id="first")))
    state, initial = start_episode(config, engine)
    assert initial["electrical"]["served_kw"] == pytest.approx(2550, abs=0.001)
    estimate = state.telemetry.estimates["a1"]
    state, failed = advance_episode(state, engine)
    assert failed["electrical"]["unserved_kw"] == pytest.approx(400, abs=0.001)
    assert state.telemetry.estimates["a1"] == estimate
    assert state.telemetry.latest["load:a1/active_power_kw"].value == 0
    assert state.telemetry.latest["load:a1/active_power_kw"].quality == "deenergized"
    assert {a.rule for a in state.rules.alarms.values()} == {
        "equipment_unavailable",
        "supply_interrupted",
    }
    state, repaired = advance_episode(state, engine)
    assert not state.physical.equipment_outages
    assert "tx_a1" in state.physical.open_transformers
    assert repaired["electrical"]["unserved_kw"] == pytest.approx(400, abs=0.001)
    alarms = list(state.rules.alarms.values())
    assert next(a for a in alarms if a.rule == "equipment_unavailable").cleared_at_s == 2
    assert next(a for a in alarms if a.rule == "supply_interrupted").cleared_at_s is None
    held = next(r for r in controller_view(state)["demand_estimates"] if r["load_id"] == "a1")
    assert held["kw"] == estimate.kw and held["age_s"] == 2
    assert held["uncertainty_pct"] == 14


def test_same_tick_repair_and_refault_never_exposes_a_healthy_intermediate_state(engine):
    config = EpisodeConfig(
        horizon_s=3, events=(trip(), trip(2, "second"), RepairEvent(at_s=2, incident_id="first"))
    )
    state, _ = start_episode(config, engine)
    state, _ = advance_episode(state, engine)
    state, frame = advance_episode(state, engine)
    assert [o.incident_id for o in state.physical.equipment_outages] == ["second"]
    assert frame["alarm_changes"] == []
    assert state.telemetry.latest["transformer:tx_a1/available"].value is False


def test_overlapping_incidents_repair_only_the_named_incident(engine):
    state, _ = start_episode(
        EpisodeConfig(events=(trip(), trip(1, "second"), RepairEvent(at_s=2, incident_id="first"))),
        engine,
    )
    for _ in range(2):
        state, _ = advance_episode(state, engine)
    assert [o.incident_id for o in state.physical.equipment_outages] == ["second"]
    assert state.telemetry.latest["transformer:tx_a1/available"].value is False


@pytest.mark.parametrize(
    "events",
    [
        (trip(), trip(2, "second", "tx_b1"), trip(3, "third", "tx_c1")),
        (RepairEvent(at_s=1, incident_id="missing"),),
        (trip(), RepairEvent(at_s=1, incident_id="first")),
        (trip(), RepairEvent(at_s=2, incident_id="first"), trip(3)),
        (trip(equipment="unknown"),),
        (TransportEvent(at_s=1, equipment="bus:unknown", latency_s=1),),
    ],
)
def test_entire_schedule_rejects_invalid_incident_and_equipment_histories(events):
    with pytest.raises(ValueError):
        EpisodeConfig(events=events)


def test_schedule_checks_existing_future_events_and_does_not_mutate_on_failure(engine):
    state, _ = start_episode(
        EpisodeConfig(horizon_s=4, events=(trip(3), trip(3, "second", "tx_b1"))), engine
    )
    original = state.model_dump_json()
    with pytest.raises(ValueError, match="two simultaneous"):
        schedule(state, (trip(2, "third", "tx_c1"),))
    assert state.model_dump_json() == original
    state, _ = advance_episode(state, engine)
    for event in (trip(1, "past"), trip(5, "future")):
        with pytest.raises(ValueError, match="strictly after"):
            schedule(state, (event,))


def test_controller_view_cannot_see_hidden_demand_or_future_events_before_delivery(engine):
    config = EpisodeConfig(
        measurements=MeasurementPolicy(latency_s=3, fresh_for_s=3),
        events=(DemandEvent(at_s=1, feeder="a", factor=1.2), trip(4)),
    )
    hidden, _ = start_episode(config, engine)
    ordinary, _ = start_episode(EpisodeConfig(measurements=config.measurements), engine)
    hidden, _ = advance_episode(hidden, engine)
    ordinary, _ = advance_episode(ordinary, engine)
    assert hidden.physical != ordinary.physical
    assert hidden.last_electrical != ordinary.last_electrical
    assert controller_view(hidden) == controller_view(ordinary)
    view = controller_view(hidden)
    assert view["signals"] == [] and all(r["kw"] is None for r in view["demand_estimates"])
    assert set(view) == {
        "at_s",
        "signals",
        "demand_estimates",
        "alarms",
        "remaining_horizon_s",
        "uncertainty_model",
    }
    assert view["uncertainty_model"] == {"growth_pct_per_s": 2, "maximum_pct": 80}
    assert view["remaining_horizon_s"] == config.horizon_s - hidden.now_s


def test_out_of_order_and_duplicate_delivery_cannot_replace_newer_measurements():
    newer, older = signal(5, 0.94), signal(2, 1.0)
    state = TelemetryState(
        pending=(
            PendingSample(due_s=5, row=newer),
            PendingSample(due_s=6, row=older),
            PendingSample(due_s=6, row=newer),
        )
    )
    state, received, _ = deliver(state, 5)
    assert [r.sequence for r in received] == [5]
    state, received, audit = deliver(state, 6)
    assert not received and not state.pending
    assert state.latest[newer.sensor_id].sequence == 5
    assert all(not d["applied"] for d in audit)


def test_dropped_rows_age_instead_of_becoming_zero_and_uncertainty_is_bounded(engine):
    config = EpisodeConfig(
        measurements=MeasurementPolicy(maximum_uncertainty_pct=12),
        events=(TransportEvent(at_s=1, equipment="load:a1", latency_s=0, drop=True),),
    )
    state, _ = start_episode(config, engine)
    old = state.telemetry.estimates["a1"]
    for _ in range(3):
        state, frame = advance_episode(state, engine)
    assert frame["dropped_sequences"]
    assert state.telemetry.estimates["a1"] == old
    view = controller_view(state)
    held = next(r for r in view["demand_estimates"] if r["load_id"] == "a1")
    assert held["age_s"] == 3 and held["uncertainty_pct"] == 12
    assert held["lower_kw"] == pytest.approx(old.kw * 0.88)
    assert not next(r for r in view["signals"] if r["sensor_id"] == "load:a1/active_power_kw")[
        "fresh"
    ]


def test_demand_estimate_requires_matching_constant_pq_voltage_timestamp(engine):
    state, _ = start_episode(EpisodeConfig(), engine)
    telemetry = state.telemetry
    latest = dict(telemetry.latest)
    key = "load:a1/active_power_kw"
    latest[key] = latest[key].model_copy(
        update={"value": 900.0, "measured_at_s": 1, "received_at_s": 1}
    )
    changed = telemetry.model_copy(update={"latest": latest})
    assert (
        estimate_demand(changed, engine.network, 1, state.config.measurements).estimates
        == telemetry.estimates
    )
    for key in ("load:a1/energized", "bus:a1_lv/voltage_min_pu", "bus:a1_lv/voltage_max_pu"):
        latest[key] = latest[key].model_copy(update={"measured_at_s": 1, "received_at_s": 1})
    latest["bus:a1_lv/voltage_min_pu"] = latest["bus:a1_lv/voltage_min_pu"].model_copy(
        update={"value": 0.9}
    )
    changed = telemetry.model_copy(update={"latest": latest})
    updated = estimate_demand(changed, engine.network, 1, state.config.measurements)
    assert updated.estimates["a1"].kw == 900
    latest["bus:a1_lv/voltage_min_pu"] = latest["bus:a1_lv/voltage_min_pu"].model_copy(
        update={"value": 0.7}
    )
    changed = telemetry.model_copy(update={"latest": latest})
    assert (
        estimate_demand(changed, engine.network, 1, state.config.measurements).estimates
        == telemetry.estimates
    )


def test_numeric_rules_require_fresh_evidence_and_hysteresis_before_clearing():
    state, policy, settings = RuleState(), MeasurementPolicy(), RuleSettings()
    rows = []
    for i, value in enumerate((0.95, 0.94, 0.93, 0.955, 0.96, 0.97, 0.98), 1):
        row = signal(i, value)
        rows.append(row)
        state, _ = update_rules(state, {row.sensor_id: row}, (row,), i, policy, settings)
        if i < 3:
            assert not state.alarms
        if i == 3:
            alarm = next(iter(state.alarms.values()))
            assert alarm.trigger_rows == tuple(rows[1:3])
            assert alarm.limit == 0.95 and alarm.reset_value == 0.96
        if 3 <= i < 7:
            assert next(iter(state.alarms.values())).cleared_at_s is None
    alarm = next(iter(state.alarms.values()))
    assert alarm.cleared_at_s == 7 and alarm.clear_rows == tuple(rows[4:7])


@pytest.mark.parametrize("quality", ["invalid", "deenergized", "stale"])
def test_invalid_or_stale_data_breaks_streak_but_cannot_clear_an_active_alarm(quality):
    state, policy, settings = RuleState(), MeasurementPolicy(), RuleSettings()
    for i in (1, 2):
        row = signal(i, 0.9)
        state, _ = update_rules(state, {row.sensor_id: row}, (row,), i, policy, settings)
    for i in (3, 4, 5):
        row = signal(
            i,
            1.0,
            measured=0 if quality == "stale" else i,
            quality="valid" if quality == "stale" else quality,
        )
        state, changes = update_rules(state, {row.sensor_id: row}, (row,), i, policy, settings)
        assert not changes
    assert next(iter(state.alarms.values())).cleared_at_s is None


def test_duplicate_rule_evidence_cannot_raise_an_alarm():
    row = signal(1, 0.9)
    state = RuleState()
    for _ in range(3):
        state, _ = update_rules(
            state, {row.sensor_id: row}, (row,), 1, MeasurementPolicy(), RuleSettings()
        )
    assert not state.alarms


@pytest.mark.parametrize("failure", ["nonconvergence", "dss"])
def test_native_failure_marks_unknown_values_and_keeps_previous_demand(
    engine, monkeypatch, failure
):
    state, _ = start_episode(EpisodeConfig(), engine)
    if failure == "dss":

        def fail(_):
            raise DSSException(1, "Test failure")

        monkeypatch.setattr(engine, "solve", fail)
    else:
        original = engine.solve
        monkeypatch.setattr(
            engine,
            "solve",
            lambda physical: original(physical).model_copy(update={"converged": False}),
        )
    changed, frame = advance_episode(state, engine)
    assert changed.now_s == 1 and frame["electrical"] is None and changed.last_error
    native = [r for r in frame["sampled_rows"] if r["source"] == "OpenDSS"]
    assert native and all(r["quality"] == "invalid" and r["value"] is None for r in native)
    assert changed.telemetry.estimates == state.telemetry.estimates


def test_native_high_load_drives_overload_rules_from_delivered_rows(engine):
    config = EpisodeConfig(initial_factors={"a": 2, "b": 2, "c": 2})
    state, _ = start_episode(config, engine)
    assert not state.rules.alarms  # first numerical sample only
    state, frame = advance_episode(state, engine)
    overloads = [a for a in state.rules.alarms.values() if a.rule == "overload"]
    assert overloads
    for alarm in overloads:
        assert all(r.value > alarm.limit for r in alarm.trigger_rows)
        assert alarm.trigger_rows[-1].model_dump(mode="json") in [
            d["row"] for d in frame["deliveries"]
        ]
