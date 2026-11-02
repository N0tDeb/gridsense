"""Stateful restoration from delivered evidence and correlated confirmations."""

import json
from typing import Literal

from pydantic import Field, model_validator

from .domain import Record
from .network import load_network
from .restoration import PlanningTiming, check_sequence, plan, planning_view, section_loads
from .switching import Command, SwitchOperation, device_positions, normal_positions, position_key


class ControlSettings(Record):
    policy: Literal["off", "nominal", "guarded"] = "off"
    max_operations: int = Field(default=3, ge=1, le=3, strict=True)
    evaluation_budget: int = Field(default=2048, ge=1, le=4096, strict=True)
    confirmation_timeout_s: int = Field(default=5, ge=1, le=30, strict=True)
    max_attempts_per_position: int = Field(default=2, ge=1, le=3, strict=True)
    max_commands: int = Field(default=24, ge=1, le=32, strict=True)
    max_decisions: int = Field(default=32, ge=1, le=64, strict=True)
    replan_interval_s: int = Field(default=2, ge=1, le=10, strict=True)
    auto_return_normal: bool = True
    planning_timing: PlanningTiming = Field(default_factory=PlanningTiming)

    @model_validator(mode="after")
    def timing_fits_confirmation(self):
        if self.planning_timing.step_s > self.confirmation_timeout_s:
            raise ValueError("Assumed actuation and feedback must fit the confirmation timeout")
        return self


class ControlState(Record):
    commands: dict[str, Command] = Field(default_factory=dict)
    pending_id: str | None = None
    remaining: tuple[SwitchOperation, ...] = ()
    plan_id: str | None = None
    last_plan: dict | None = None
    last_signature: str | None = None
    last_planned_at_s: int = -100
    last_unavailable: tuple[str, ...] = ()
    recovery_requested: bool = False
    unsafe_positions: tuple[str, ...] = ()
    unsafe_exposures: tuple[dict, ...] = ()
    demand_signature: str | None = None
    decision_count: int = 0
    native_evaluations: int = 0
    status: str = "off"
    reason: str = "Automatic switching is disabled"
    supply_status: str = "awaiting_measurements"


def supply_status(observation, network):
    """Supply is assessed from native rows, never a successful command alone."""
    rows = {r["sensor_id"]: r for r in observation["signals"]}

    def current(key):
        row = rows.get(key)
        return row if row and row["fresh"] else None

    supplied = 0
    for load in network["loads"]:
        row = current("load:" + load["id"] + "/energized")
        if row is None:
            return "awaiting_measurements"
        if row["value"] is False:
            continue
        evidence = [
            current("load:" + load["id"] + "/active_power_kw"),
            current("bus:" + load["bus"] + "_lv/voltage_min_pu"),
            current("bus:" + load["bus"] + "_lv/voltage_max_pu"),
        ]
        if any(r is None or r["measured_at_s"] != row["measured_at_s"] for r in evidence):
            return "awaiting_measurements"
        power, low, high = (r["value"] for r in evidence)
        if power <= 0 or not 0.95 <= low <= high <= 1.05:
            return "electrical_limits_violated"
        supplied += 1
    normal = normal_positions(network)
    for asset in normal:
        if asset.startswith(("line:", "transformer:")):
            row = current(asset + "/loading_pct")
            if row is None:
                return "awaiting_measurements"
            if row["value"] > 100 + 1e-6:
                return "electrical_limits_violated"
    if supplied < len(network["loads"]):
        return "partial_supply_verified" if supplied else "supply_interrupted"
    positions = {asset: current(asset + "/closed") for asset in normal}
    if any(row is None for row in positions.values()):
        return "awaiting_measurements"
    return (
        "normal_supply_verified"
        if all(positions[asset]["value"] == value for asset, value in normal.items())
        else "alternate_supply_verified"
    )


def encoded_position(state, network):
    return json.dumps(position_key(state, network), separators=(",", ":"))


def update_control(control, settings, observation, engine, *, enabled=True):
    """No scenario events, actuator settings or physical load factors are accepted."""
    network, now = load_network(), observation["at_s"]
    changes = []
    control = control.model_copy(update={"supply_status": supply_status(observation, network)})

    def stop(status, reason):
        return control.model_copy(update={"status": status, "reason": reason}), None, changes

    if settings.policy == "off":
        return stop("off", "Automatic switching is disabled")
    if not enabled:
        return stop("paused", "No new commands at the horizon or while the native solve is unknown")
    force = False
    confirmed = None
    if control.pending_id:
        command = control.commands[control.pending_id]
        if command.status in {"pending", "unknown"}:
            return stop(
                "confirmation_pending" if command.status == "pending" else "confirmation_unknown",
                "Waiting for correlated position feedback; further switching is blocked",
            )
        confirmed = command if command.status == "confirmed" else None
        remaining = control.remaining if confirmed else ()
        control = control.model_copy(
            update={"pending_id": None, "remaining": remaining, "last_signature": None}
        )
        force = True
        changes.append(
            {"kind": "command_settled", "command_id": command.id, "status": command.status}
        )
    try:
        view = planning_view(observation, network)
    except ValueError as exc:
        # Keep a confirmed plan pending fresh position evidence, but issue nothing.
        if confirmed:
            control = control.model_copy(update={"pending_id": confirmed.id})
        return stop("insufficient_information", str(exc))
    unavailable = tuple(sorted(o.kind + ":" + o.equipment for o in view.state.equipment_outages))
    # Newly observed faults, repairs and overload changes supersede a time-only
    # cooldown. The pending-confirmation block above still applies.
    force = force or unavailable != control.last_unavailable
    previous_overloads = (control.last_plan or {}).get("measured_overloads", ())
    force = force or {r["equipment"] for r in view.measured_overloads} != {
        r["equipment"] for r in previous_overloads
    }
    repaired = set(control.last_unavailable) - set(unavailable)
    recovery = control.recovery_requested or bool(repaired and settings.auto_return_normal)
    if device_positions(view.state, network) == normal_positions(network):
        recovery = False
    demand_signature = json.dumps({k: round(v, 0) for k, v in sorted(view.demand_kw.items())})
    unsafe = (
        set(control.unsafe_positions) if demand_signature == control.demand_signature else set()
    )
    exposures = {
        json.dumps({k: v for k, v in item.items() if k != "row"}, sort_keys=True): item
        for item in control.unsafe_exposures
        if all(round(view.demand_kw[key], 0) == value for key, value in item["demand_kw"].items())
    }
    for overload in view.measured_overloads:
        loads = sorted(section_loads(view.state, overload["equipment"], network))
        if not loads:
            continue
        item = {
            "equipment": overload["equipment"],
            "load_ids": loads,
            "demand_kw": {key: round(view.demand_kw[key], 0) for key in loads},
            "row": overload["row"],
        }
        key = json.dumps({k: v for k, v in item.items() if k != "row"}, sort_keys=True)
        exposures[key] = item
        unsafe.add(encoded_position(view.state, network))
    view = view.model_copy(
        update={"unsafe_exposures": tuple(exposures[key] for key in sorted(exposures))}
    )
    active = [a for a in observation["alarms"] if a["cleared_at_s"] is None]
    rows = {r["sensor_id"]: r for r in observation["signals"]}
    position_times = {r[1]["measured_at_s"] for r in view.evidence["device_rows"].values()}
    for alarm in active:
        row = rows.get(alarm["sensor_id"])
        if alarm["rule"] not in {"overload", "low_voltage", "high_voltage"}:
            continue
        if row and row["fresh"] and position_times == {row["measured_at_s"]}:
            violates = (
                row["value"] < alarm["limit"]
                if alarm["rule"] == "low_voltage"
                else row["value"] > alarm["limit"]
            )
            if violates:
                unsafe.add(encoded_position(view.state, network))
    control = control.model_copy(
        update={
            "last_unavailable": unavailable,
            "recovery_requested": recovery,
            "unsafe_positions": tuple(sorted(unsafe)),
            "unsafe_exposures": view.unsafe_exposures,
            "demand_signature": demand_signature,
        }
    )
    forbidden = tuple(tuple((asset, value) for asset, value in json.loads(key)) for key in unsafe)
    if confirmed and control.remaining:
        pair = view.evidence["device_rows"][confirmed.operation.equipment]
        if pair[1]["measured_at_s"] < confirmed.measured_at_s:
            # Keep correlation until position telemetry catches up; don't consume twice.
            control = control.model_copy(update={"pending_id": confirmed.id})
            return stop("insufficient_information", "Position telemetry predates the confirmation")
        if pair[1]["value"] != confirmed.operation.closed:
            control = control.model_copy(update={"remaining": ()})
            changes.append(
                {"kind": "plan_cancelled", "reason": "A newer position superseded the confirmation"}
            )
    available_budget = settings.evaluation_budget
    if control.remaining:
        checked = check_sequence(
            view,
            control.remaining,
            settings.policy,
            budget=settings.evaluation_budget,
            engine=engine,
            forbidden=forbidden,
            timing=settings.planning_timing,
        )
        control = control.model_copy(
            update={
                "native_evaluations": control.native_evaluations + checked["native_evaluations"]
            }
        )
        changes.append({"kind": "sequence_revalidation", **checked})
        available_budget -= checked["native_evaluations"]
        if not checked["feasible"]:
            control = control.model_copy(update={"remaining": ()})
            force = True
    attempts = {}
    for command in control.commands.values():
        attempts[command.operation.key] = attempts.get(command.operation.key, 0) + 1
    blocked = tuple(
        key for key, count in attempts.items() if count >= settings.max_attempts_per_position
    )
    if len(control.commands) >= settings.max_commands:
        return stop("command_limit", "Episode command limit reached; operator inspection required")
    if not control.remaining:
        if not active and not recovery and not view.measured_overloads:
            return stop(
                "monitoring", "No active received alarm or observed repair requires a new decision"
            )
        signature = json.dumps(
            {
                "positions": position_key(view.state, network),
                "outages": unavailable,
                "demand": demand_signature,
                # Guarded feasibility depends on bounds as well as means.
                # One-watt precision ignores native solver noise; timestamps
                # alone do not invalidate an otherwise identical decision.
                "bounds": {
                    key: [round(value, 3) for value in bounds]
                    for key, bounds in sorted(view.bounds_kw.items())
                }
                if settings.policy == "guarded"
                else None,
                "alarms": [a["id"] for a in active],
                "unsafe": sorted(unsafe),
                "unsafe_exposures": sorted(exposures),
                "blocked": blocked,
                "recovery": recovery,
                "operation_allowance": min(
                    settings.max_operations,
                    settings.max_commands - len(control.commands),
                    view.remaining_horizon_s // settings.planning_timing.step_s,
                ),
                "energy_horizon_s": min(
                    settings.planning_timing.energy_horizon_s, view.remaining_horizon_s
                ),
            },
            sort_keys=True,
        )
        if not force and (
            signature == control.last_signature
            or now - control.last_planned_at_s < settings.replan_interval_s
        ):
            return stop(
                "holding",
                "Holding the evaluated configuration until new actionable evidence arrives",
            )
        if control.decision_count >= settings.max_decisions:
            return stop(
                "decision_limit", "Episode decision limit reached; operator inspection required"
            )
        if available_budget == 0:
            return stop(
                "evaluation_limit", "Native evaluation budget consumed by sequence revalidation"
            )
        # Returning to normal must never outrank a received electrical violation.
        # Reconfigure or shed demand first; retain the recovery request for later.
        goal = (
            "normal"
            if recovery
            and not unavailable
            and control.supply_status != "electrical_limits_violated"
            and not view.measured_overloads
            else "restore"
        )
        proposal = plan(
            view,
            settings.policy,
            budget=available_budget,
            # A break-before-make sequence needs enough remaining commands to
            # finish. Do not disconnect backup on a plan the episode cap truncates.
            max_operations=min(
                settings.max_operations, settings.max_commands - len(control.commands)
            ),
            engine=engine,
            goal=goal,
            blocked=blocked,
            forbidden=forbidden,
            timing=settings.planning_timing,
        )
        plan_id = f"plan-{control.decision_count + 1}"
        selected = proposal["selected"]
        operations = (
            tuple(SwitchOperation.model_validate(r) for r in selected["operations"])
            if proposal["feasible_choice"]
            else ()
        )
        control = control.model_copy(
            update={
                "last_plan": proposal,
                "last_signature": signature,
                "last_planned_at_s": now,
                "plan_id": plan_id,
                "decision_count": control.decision_count + 1,
                "native_evaluations": control.native_evaluations + proposal["native_evaluations"],
                "remaining": operations,
            }
        )
        changes.append({"kind": "plan_evaluated", "plan_id": plan_id, "reason": proposal["reason"]})
        if not operations:
            return stop("holding", proposal["reason"])
    operation, *remaining = control.remaining
    if operation.key in blocked:
        control = control.model_copy(update={"remaining": (), "last_signature": None})
        return stop("attempt_limit", "Position attempt limit reached; remaining sequence cancelled")
    command = Command(
        id=f"command-{len(control.commands) + 1}",
        plan_id=control.plan_id,
        operation=operation,
        issued_at_s=now,
        deadline_s=now + settings.confirmation_timeout_s,
    )
    control = control.model_copy(
        update={
            "commands": {**control.commands, command.id: command},
            "pending_id": command.id,
            "remaining": tuple(remaining),
            "status": "confirmation_pending",
            "reason": "Command issued; waiting for position confirmation and electrical supply evidence",
        }
    )
    changes.append({"kind": "command_issued", "command": command.model_dump(mode="json")})
    return control, command, changes
