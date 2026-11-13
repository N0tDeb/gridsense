"""Native reproductions of missed evidence, phase attribution and metric scope."""

from copy import deepcopy
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures.process import BrokenProcessPool
from types import SimpleNamespace
import asyncio

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from gridsense.api import compute_in_pool, create_app
from gridsense.cases import PortableCase
from gridsense.control import ControlSettings, ControlState, update_control
from gridsense.domain import Action, EquipmentOutage, Operation, Scenario
from gridsense.electrical import ElectricalEngine
from gridsense.episodes import (
    EpisodeConfig,
    OutageEvent,
    TransportEvent,
    advance_episode,
    controller_view,
    start_episode,
)
from gridsense.ieee13 import IEEE13Plant, TIES
from gridsense.network import healthy_state, isolate_outage, repair_outage
from gridsense.plants import TeachingPlant
from gridsense.restoration import plan, planning_view
from gridsense.switching import Command, SwitchOperation
from gridsense.telemetry import MeasurementPolicy


@pytest.fixture(scope="module")
def engine():
    return ElectricalEngine()


@pytest.mark.parametrize("initial_uncertainty", [0, 10])
def test_fresh_donor_bounds_are_reconsidered_without_a_changed_mean(engine, initial_uncertainty):
    trip, refresh, horizon = (5, 10, 14) if initial_uncertainty == 0 else (10, 15, 19)
    factors = (
        {"a": 0.8, "b": 1.45, "c": 1.25}
        if initial_uncertainty == 0
        else {"a": 0.8, "b": 1.6, "c": 1}
    )
    assets = [
        prefix + name + suffix
        for name in ("b1", "b2", "c1", "c2")
        for prefix, suffix in (("load:", ""), ("bus:", "_lv"))
    ]
    config = EpisodeConfig(
        horizon_s=horizon,
        initial_factors=factors,
        measurements=MeasurementPolicy(initial_uncertainty_pct=initial_uncertainty),
        control=ControlSettings(policy="guarded"),
        events=(
            *(TransportEvent(at_s=1, equipment=asset, latency_s=0, drop=True) for asset in assets),
            OutageEvent(at_s=trip, incident_id="trip", equipment_kind="line", equipment="feed_a"),
            *(
                TransportEvent(at_s=refresh, equipment=asset, latency_s=0, drop=False)
                for asset in assets
            ),
        ),
    )
    state, frame = start_episode(config, engine)
    frames = [frame]
    for _ in range(config.horizon_s):
        state, frame = advance_episode(state, engine)
        frames.append(frame)
    before, fresh = (
        planning_view(frame["observation"]) for frame in frames[refresh - 1 : refresh + 1]
    )
    assert {k: round(v) for k, v in before.demand_kw.items()} == {
        k: round(v) for k, v in fresh.demand_kw.items()
    }
    assert any(fresh.bounds_kw[k][1] < before.bounds_kw[k][1] for k in ("b1", "b2", "c1", "c2"))
    decisions = [
        frame
        for frame in frames[refresh : refresh + config.control.replan_interval_s + 1]
        if any(event["kind"] == "plan_evaluated" for event in frame["control_events"])
    ]
    assert decisions
    # The new action set restores A earlier and sheds a smaller donor load.
    # Refresh must still trigger reconsideration; it does not guarantee that
    # a future-time check permits all customers to be reconnected.
    for frame in (frames[refresh - 1], frames[-1]):
        affected = [
            row
            for row in frame["electrical"]["load_measurements"]
            if row["load_id"] in {"a1", "a2"}
        ]
        assert sum(row["served_kw"] for row in affected) == pytest.approx(800, abs=0.001)
    assert frames[-1]["electrical"]["unserved_kw"] == pytest.approx(
        362.5 if initial_uncertainty == 0 else 350, abs=0.001
    )
    assert state.metrics.first_full_recovery_s is None
    assert state.metrics.unserved_kwh < 1.377778
    assert all(f["electrical"]["feasible"] for f in frames)


@pytest.mark.parametrize("policy", ["nominal", "guarded"])
@pytest.mark.parametrize("scale", [0.5, 2])
def test_bounds_change_reconsiders_only_the_policy_that_uses_them(
    engine, monkeypatch, policy, scale
):
    state, _ = start_episode(
        EpisodeConfig(
            events=(
                OutageEvent(at_s=1, incident_id="trip", equipment_kind="line", equipment="feed_a"),
            )
        ),
        engine,
    )
    state, _ = advance_episode(state, engine)
    observation = controller_view(state)
    # The planner still evaluates native physics; the test suppresses selection
    # to isolate the trigger from command settlement and position changes.
    calls = []

    def hold(view, selected_policy, **kwargs):
        result = plan(view, selected_policy, **kwargs)
        result["feasible_choice"] = False
        calls.append(result)
        return result

    monkeypatch.setattr("gridsense.control.plan", hold)
    settings = ControlSettings(policy=policy)
    control, command, _ = update_control(ControlState(), settings, observation, engine)
    assert command is None and len(calls) == 1
    same = deepcopy(observation)
    same["at_s"] += 2
    unchanged, _, _ = update_control(control, settings, same, engine)
    assert len(calls) == 1 and unchanged.last_planned_at_s == control.last_planned_at_s
    changed = deepcopy(same)
    for row in changed["demand_estimates"]:
        row["lower_kw"] = row["kw"] - (row["kw"] - row["lower_kw"]) * scale
        row["upper_kw"] = row["kw"] + (row["upper_kw"] - row["kw"]) * scale
    updated, _, _ = update_control(control, settings, changed, engine)
    assert len(calls) == (2 if policy == "guarded" else 1)
    if policy == "guarded":
        assert updated.last_planned_at_s == changed["at_s"]


def test_changed_bounds_respect_cooldown_and_pending_confirmation(engine, monkeypatch):
    state, _ = start_episode(
        EpisodeConfig(
            events=(
                OutageEvent(at_s=1, incident_id="trip", equipment_kind="line", equipment="feed_a"),
            )
        ),
        engine,
    )
    state, _ = advance_episode(state, engine)
    observation = controller_view(state)

    def hold(view, policy, **kwargs):
        result = plan(view, policy, **kwargs)
        result["feasible_choice"] = False
        return result

    monkeypatch.setattr("gridsense.control.plan", hold)
    settings = ControlSettings(policy="guarded")
    control, _, _ = update_control(ControlState(), settings, observation, engine)
    changed = deepcopy(observation)
    changed["at_s"] += 1
    changed["demand_estimates"][0]["upper_kw"] += 20
    cooled, command, events = update_control(control, settings, changed, engine)
    assert command is None and cooled.decision_count == control.decision_count and not events
    pending = Command(
        id="waiting",
        plan_id="p",
        operation=SwitchOperation(equipment="line:tie_b", closed=True),
        issued_at_s=1,
        deadline_s=6,
    )
    control = control.model_copy(
        update={"pending_id": pending.id, "commands": {pending.id: pending}}
    )
    changed["at_s"] += 2
    blocked, command, events = update_control(control, settings, changed, engine)
    assert command is None and not events and blocked.commands == control.commands
    assert blocked.status == "confirmation_pending"


@pytest.fixture(scope="module")
def healthy_ieee():
    plant = IEEE13Plant(
        PortableCase(
            feeder="ieee13",
            fault="671692",
            scenario=Scenario(load_b=1, reported_b=1, telemetry_age_s=0),
        )
    )
    state = plant.truth.model_copy(
        update={"closed_lines": tuple(sorted(set(plant.lines) - set(TIES))), "locked_open": ()}
    )
    return plant, state, plant.solve(state)


def test_ieee_single_phase_row_uses_its_connected_phase_and_retains_raw_power(healthy_ieee):
    _, _, result = healthy_ieee
    row = next(r for r in result.load_measurements if r["load_id"] == "675b")
    assert row["voltage_pu"] == pytest.approx(result.voltages_pu["675.2"], abs=1e-10)
    assert row["voltage_pu"] > 1.05 and row["bus_min_voltage_pu"] < 0.98
    assert row["phase_nodes"] == [2, 0] and row["voltage_basis"] == "phase-to-neutral"
    assert row["voltage_on_load_base_pu"]["2-0"] > row["voltage_pu"]
    assert row["native_kw"] > row["served_kw"] == row["requested_kw"]
    assert row["native_kvar"] > 60 and row["quality"] == "solved"


@pytest.mark.parametrize("name,pair", [("646", "2-3"), ("692", "3-1"), ("671", "1-2")])
def test_ieee_delta_voltage_is_a_branch_phasor_difference(healthy_ieee, name, pair):
    _, _, result = healthy_ieee
    row = next(r for r in result.load_measurements if r["load_id"] == name)
    assert row["connection"] == "delta" and row["voltage_basis"] == "phase-to-phase"
    assert row["voltage_branches_v"][pair] > 3900
    assert row["voltage_branches_pu"][pair] == pytest.approx(row["voltage_branches_v"][pair] / 4160)
    assert row["voltage_pu"] == min(row["voltage_branches_pu"].values())
    assert row["voltage_pu"] != pytest.approx(row["bus_min_voltage_pu"], abs=1e-4)


def test_ieee_disconnected_and_unconverged_rows_do_not_claim_measurement_quality(
    healthy_ieee, monkeypatch
):
    plant, _, _ = healthy_ieee
    result = plant.solve(plant.truth)
    row = next(r for r in result.load_measurements if r["load_id"] == "675b")
    assert not row["energized"] and row["served_kw"] == row["native_kw"] == row["voltage_pu"] == 0
    assert not row["voltage_compliant"]
    monkeypatch.setattr(type(ElectricalEngine().ctx.Solution), "Converged", lambda self: False)
    unknown = plant.solve(plant.truth)
    assert not unknown.feasible and unknown.restored_kw == 0
    assert all(
        r["native_kw"] is r["native_kvar"] is None and r["quality"] == "unconverged"
        for r in unknown.load_measurements
    )


def test_generic_electrical_results_do_not_assign_incident_credit_to_feeder_a(engine):
    healthy = healthy_state()
    result = engine.solve(healthy)
    assert result.restored_kw == 0 and result.restoration_baseline_kw == {}
    faulted = isolate_outage(
        healthy, EquipmentOutage(incident_id="east", kind="transformer", equipment="tx_c1")
    )
    disconnected = engine.solve(faulted)
    assert disconnected.restored_kw == 0 and disconnected.unserved_kw == pytest.approx(
        500, abs=0.001
    )
    repaired = repair_outage(faulted, "east").model_copy(update={"open_transformers": ()})
    supplied = engine.solve(repaired).with_restoration_baseline({"c1": 0})
    assert supplied.restored_kw == pytest.approx(500, abs=0.001)
    assert supplied.restoration_baseline_kw == {"c1": 0}
    partial = supplied.with_restoration_baseline({"c1": 200})
    assert partial.restored_kw == pytest.approx(300, abs=0.001)
    with pytest.raises(ValueError, match="known loads"):
        supplied.with_restoration_baseline({"missing": 0})
    with pytest.raises(ValueError, match="nonnegative"):
        supplied.with_restoration_baseline({"c1": -1})


@pytest.mark.parametrize(
    "fault,baseline,expected", [("feed_a", {"a1": 0, "a2": 0}, 1000), ("seg_a", {"a2": 0}, 0)]
)
def test_teaching_snapshot_assigns_the_actual_affected_loads(fault, baseline, expected):
    plant = TeachingPlant(PortableCase(fault=fault))
    assert plant.solve(plant.truth).restoration_baseline_kw == baseline
    action = Action(
        id="restore",
        label="restore",
        operations=(Operation(line="tie_c", closed=True),) if fault == "feed_a" else (),
    )
    result = plant.execute(plant.truth, action).result
    assert result.restored_kw == pytest.approx(expected, abs=0.1)
    assert result.restoration_baseline_kw == baseline


def test_broken_pool_changes_readiness_and_restart_recovers_it(tmp_path):
    class Broken:
        calls = 0

        def submit(self, *args):
            self.calls += 1
            raise BrokenProcessPool("injected worker failure")

    app = create_app(tmp_path)
    with TestClient(app) as client:
        assert client.get("/api/health").status_code == 200
        original, broken = app.state.pool, Broken()
        app.state.pool = broken
        try:
            assert client.post("/api/incidents", json={}).status_code == 503
            health = client.get("/api/health")
            assert health.status_code == 503 and health.json()["status"] == "unavailable"
            assert health.json()["workers"] == 0
            assert client.post("/api/incidents", json={}).status_code == 503
            assert broken.calls == 1 and not app.state.slots.locked()
        finally:
            app.state.pool = original
    with TestClient(create_app(tmp_path)) as restarted:
        assert restarted.get("/api/health").json()["status"] == "ready"


def test_worker_failure_after_caller_cancellation_still_marks_pool_unavailable():
    async def check():
        import threading

        started, release = threading.Event(), threading.Event()
        with ThreadPoolExecutor(max_workers=1) as pool:
            app = SimpleNamespace(
                state=SimpleNamespace(
                    pool=pool, slots=asyncio.Semaphore(1), worker_pool_available=True
                )
            )

            def work():
                started.set()
                assert release.wait(5)
                raise BrokenProcessPool("late injected failure")

            task = asyncio.create_task(compute_in_pool(app, work))
            while not started.is_set():
                await asyncio.sleep(0.001)
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
            release.set()
            for _ in range(1000):
                if not app.state.worker_pool_available:
                    break
                await asyncio.sleep(0.001)
            assert not app.state.worker_pool_available and not app.state.slots.locked()
            with pytest.raises(HTTPException) as error:
                await compute_in_pool(app, int, "7")
            assert error.value.status_code == 503

    asyncio.run(check())
