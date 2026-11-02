"""Integer-second native episodes. Physical changes precede delivered information."""

import hashlib
import json
from importlib.resources import files
from itertools import groupby
from typing import Annotated, Literal

from dss import DSSException
from pydantic import Field, model_validator

from .control import ControlSettings, ControlState, update_control
from .domain import CircuitState, EquipmentOutage, Record
from .electrical import ElectricalEngine
from .episode_metrics import EpisodeMetrics, integrate_interval, observe_outcome
from .network import healthy_state, isolate_outage, load_network, network_hash, repair_outage
from .rules import RuleSettings, RuleState, update_rules
from .switching import (
    Actuation,
    PositionFeedback,
    change_position,
    confirm_commands,
    device_positions,
)
from .telemetry import (
    MeasurementPolicy,
    PendingSample,
    TelemetryState,
    deliver,
    equipment_ids,
    estimate_demand,
    native_samples,
    observation_rows,
)

ORDERING = (
    "physical-repairs-and-events/actuate/solve/sample/deliver/confirm-timeout/rules/control-v2"
)


class TimedEvent(Record):
    at_s: int = Field(ge=1, le=600, strict=True)


class OutageEvent(TimedEvent):
    kind: Literal["outage"] = "outage"
    incident_id: str = Field(min_length=1, max_length=64)
    equipment_kind: Literal["line", "transformer", "source"]
    equipment: str = Field(min_length=1, max_length=64)


class RepairEvent(TimedEvent):
    kind: Literal["repair"] = "repair"
    incident_id: str = Field(min_length=1, max_length=64)


class DemandEvent(TimedEvent):
    kind: Literal["demand"] = "demand"
    feeder: Literal["a", "b", "c"]
    factor: float = Field(ge=0.5, le=2)


class TransportEvent(TimedEvent):
    kind: Literal["transport"] = "transport"
    equipment: str = Field(min_length=1, max_length=80)
    latency_s: int = Field(ge=0, le=30, strict=True)
    drop: bool = False


class ActuatorEvent(TimedEvent):
    kind: Literal["actuator"] = "actuator"
    equipment: str = Field(min_length=1, max_length=80)
    actuation_delay_s: int = Field(default=1, ge=1, le=10, strict=True)
    fail: bool = False
    feedback_delay_s: int = Field(default=0, ge=0, le=30, strict=True)
    drop_feedback: bool = False
    duplicates: int = Field(default=0, ge=0, le=2, strict=True)
    duplicate_delay_s: int = Field(default=1, ge=1, le=10, strict=True)


Event = Annotated[
    OutageEvent | RepairEvent | DemandEvent | TransportEvent | ActuatorEvent,
    Field(discriminator="kind"),
]


class QueuedEvent(Record):
    sequence: int
    event: Event


class EpisodeConfig(Record):
    title: str = Field(default="Live teaching feeder", min_length=1, max_length=100)
    horizon_s: int = Field(default=30, ge=1, le=600, strict=True)
    initial_factors: dict[str, float] = Field(default_factory=lambda: {"a": 1, "b": 1, "c": 1})
    measurements: MeasurementPolicy = Field(default_factory=MeasurementPolicy)
    rules: RuleSettings = Field(default_factory=RuleSettings)
    control: ControlSettings = Field(default_factory=ControlSettings)
    events: tuple[Event, ...] = Field(default=(), max_length=128)

    @model_validator(mode="after")
    def validate_definition(self):
        if set(self.initial_factors) != {"a", "b", "c"} or any(
            not 0.5 <= value <= 2 for value in self.initial_factors.values()
        ):
            raise ValueError("Initial factors a, b and c must be between 0.5 and 2")
        validate_schedule(
            healthy_state(self.initial_factors),
            tuple(QueuedEvent(sequence=i, event=e) for i, e in enumerate(self.events)),
            0,
            self.horizon_s,
            (),
        )
        return self


class EpisodeState(Record):
    now_s: int
    config: EpisodeConfig
    physical: CircuitState
    future: tuple[QueuedEvent, ...]
    next_event_sequence: int
    used_incident_ids: tuple[str, ...] = ()
    transport: dict[str, TransportEvent] = Field(default_factory=dict)
    telemetry: TelemetryState = Field(default_factory=TelemetryState)
    rules: RuleState = Field(default_factory=RuleState)
    control: ControlState = Field(default_factory=ControlState)
    actuators: dict[str, ActuatorEvent] = Field(default_factory=dict)
    actuations: tuple[Actuation, ...] = ()
    feedback: tuple[PositionFeedback, ...] = ()
    next_feedback_sequence: int = 0
    metrics: EpisodeMetrics = Field(default_factory=EpisodeMetrics)
    last_electrical: dict | None = None
    last_error: str | None = None
    manifest: dict


def canonical_hash(value):
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    ).hexdigest()


def episode_hash():
    root = files("gridsense")
    names = (
        "domain.py",
        "electrical.py",
        "network.py",
        "episodes.py",
        "telemetry.py",
        "rules.py",
        "control.py",
        "restoration.py",
        "switching.py",
        "episode_metrics.py",
        "session_store.py",
        "session_api.py",
        "service.py",
    )
    return hashlib.sha256(
        b"".join(name.encode() + root.joinpath(name).read_bytes() for name in names)
    ).hexdigest()


def validate_schedule(physical, events, now_s, horizon_s, used_ids):
    if len(events) > 128:
        raise ValueError("At most 128 pending physical/transport events are supported")
    used = set(used_ids)
    network = load_network()
    ordered = sorted(events, key=lambda q: (q.event.at_s, q.sequence))
    if len({q.sequence for q in ordered}) != len(ordered):
        raise ValueError("Event sequence numbers must be unique")
    for at_s, group in groupby(ordered, key=lambda q: q.event.at_s):
        if not now_s < at_s <= horizon_s:
            raise ValueError(
                "Schedule events strictly after the current tick and within the horizon"
            )
        items = list(group)
        # Clear only incidents active before this timestamp. A new incident
        # cannot be created and repaired in the same tick.
        for item in items:
            if item.event.kind == "repair":
                physical = repair_outage(physical, item.event.incident_id)
        for item in items:
            event = item.event
            if event.kind == "outage":
                if event.incident_id in used:
                    raise ValueError("Incident IDs cannot be reused within an episode")
                physical = isolate_outage(
                    physical,
                    EquipmentOutage(
                        incident_id=event.incident_id,
                        kind=event.equipment_kind,
                        equipment=event.equipment,
                    ),
                )
                used.add(event.incident_id)
            elif event.kind == "transport" and event.equipment not in equipment_ids(network):
                raise ValueError("Unknown telemetry equipment")
            elif event.kind == "actuator" and event.equipment not in device_positions(
                physical, network
            ):
                raise ValueError("Unknown switchable equipment")
        if len(physical.equipment_outages) > 2:
            raise ValueError("At most two simultaneous equipment incidents are supported")


def schedule(state, events):
    queued = tuple(
        QueuedEvent(sequence=state.next_event_sequence + i, event=e) for i, e in enumerate(events)
    )
    future = (*state.future, *queued)
    validate_schedule(
        state.physical, future, state.now_s, state.config.horizon_s, state.used_incident_ids
    )
    return state.model_copy(
        update={
            "future": tuple(sorted(future, key=lambda q: (q.event.at_s, q.sequence))),
            "next_event_sequence": state.next_event_sequence + len(queued),
        }
    )


def snapshot(state, engine, applied, actuation_events=()):
    result, error = None, None
    try:
        result = engine.solve(state.physical)
        if not result.converged:
            result, error = None, "OpenDSS did not converge; electrical measurements are unknown"
    except DSSException:
        error = "OpenDSS solve failed; electrical measurements are unknown"
    telemetry, samples, dropped = state.telemetry, (), []
    policy = state.config.measurements
    if state.now_s % policy.period_s == 0:
        samples = native_samples(
            engine, state.physical, result, state.now_s, telemetry.next_sequence
        )
        pending = list(telemetry.pending)
        for row in samples:
            override = state.transport.get(row.equipment)
            if override and override.drop:
                dropped.append(row.sequence)
                continue
            delay = override.latency_s if override else policy.latency_s
            pending.append(PendingSample(due_s=state.now_s + delay, row=row))
        telemetry = telemetry.model_copy(
            update={
                "pending": tuple(pending),
                "next_sequence": telemetry.next_sequence + len(samples),
            }
        )
    telemetry, received, deliveries = deliver(telemetry, state.now_s)
    telemetry = estimate_demand(telemetry, engine.network, state.now_s, policy)
    commands, feedback, confirmations = confirm_commands(
        state.control.commands, state.feedback, state.now_s
    )
    rules, changes = update_rules(
        state.rules, telemetry.latest, received, state.now_s, policy, state.config.rules
    )
    electrical = result.model_dump(mode="json") if result is not None else None
    state = state.model_copy(
        update={
            "telemetry": telemetry,
            "rules": rules,
            "last_electrical": electrical,
            "last_error": error,
            "feedback": feedback,
            "control": state.control.model_copy(update={"commands": commands}),
            "metrics": observe_outcome(state.metrics, electrical, state.now_s),
        }
    )
    control, command, control_events = update_control(
        state.control,
        state.config.control,
        controller_view(state),
        engine,
        enabled=error is None and state.now_s < state.config.horizon_s,
    )
    actuations = state.actuations
    if command:
        override = state.actuators.get(command.operation.equipment)
        delay = override.actuation_delay_s if override else 1
        actuations = (*actuations, Actuation(command_id=command.id, due_s=state.now_s + delay))
    state = state.model_copy(update={"control": control, "actuations": actuations})
    frame = {
        "at_s": state.now_s,
        "physical_events": [q.model_dump(mode="json") for q in applied],
        "physical": state.physical.model_dump(mode="json"),
        "electrical": electrical,
        "solver_error": error,
        "sampled_rows": [r.model_dump(mode="json") for r in samples],
        "dropped_sequences": dropped,
        "deliveries": deliveries,
        "alarm_changes": changes,
        "observation": controller_view(state),
        "actuation_events": list(actuation_events),
        "confirmation_events": confirmations,
        "control_events": control_events,
        "control": control.model_dump(mode="json"),
        "metrics": state.metrics.model_dump(mode="json"),
    }
    return state, frame


def start_episode(config, engine=None):
    engine = engine or ElectricalEngine()
    state = EpisodeState(
        now_s=0,
        config=config,
        physical=healthy_state(config.initial_factors),
        future=tuple(QueuedEvent(sequence=i, event=e) for i, e in enumerate(config.events)),
        next_event_sequence=len(config.events),
        manifest={
            "schema_version": 1,
            "episode_sha256": episode_hash(),
            "network_sha256": network_hash(engine.network),
            "solver_version": engine.version,
            "ordering": ORDERING,
            "tick_seconds": 1,
            "random_seed": None,
            "noise_model": "No stochastic noise; exact native samples with explicit delay/drop settings",
        },
    )
    return snapshot(state, engine, ())


def advance_episode(state, engine=None):
    if state.now_s >= state.config.horizon_s:
        raise ValueError("The recorded episode horizon has been reached")
    engine = engine or ElectricalEngine()
    assert_compatible(state, engine)
    at_s, physical = state.now_s + 1, state.physical
    due = sorted((q for q in state.future if q.event.at_s == at_s), key=lambda q: q.sequence)
    used, transport, actuators = (
        set(state.used_incident_ids),
        dict(state.transport),
        dict(state.actuators),
    )
    for item in due:
        if item.event.kind == "repair":
            physical = repair_outage(physical, item.event.incident_id)
    for item in due:
        event = item.event
        if event.kind == "outage":
            physical = isolate_outage(
                physical,
                EquipmentOutage(
                    incident_id=event.incident_id,
                    kind=event.equipment_kind,
                    equipment=event.equipment,
                ),
            )
            used.add(event.incident_id)
        elif event.kind == "demand":
            physical = physical.model_copy(
                update={"load_factors": {**physical.load_factors, event.feeder: event.factor}}
            )
        elif event.kind == "transport":
            transport[event.equipment] = event
        elif event.kind == "actuator":
            actuators[event.equipment] = event
    updated = state.model_copy(
        update={
            "now_s": at_s,
            "physical": physical,
            "transport": transport,
            "actuators": actuators,
            "metrics": integrate_interval(state.metrics, state.last_electrical),
            "used_incident_ids": tuple(sorted(used)),
            "future": tuple(q for q in state.future if q.event.at_s > at_s),
        }
    )
    updated, actuation_events = actuate(updated, engine.network)
    return snapshot(updated, engine, due, actuation_events)


def actuate(state, network):
    """Private physical executor. Never used to assess planning feasibility."""
    physical, feedback, sequence, audit = (
        state.physical,
        list(state.feedback),
        state.next_feedback_sequence,
        [],
    )
    attempts, changes = 0, 0
    for queued in sorted(state.actuations, key=lambda r: (r.due_s, r.command_id)):
        if queued.due_s > state.now_s:
            continue
        command = state.control.commands[queued.command_id]
        override = state.actuators.get(command.operation.equipment)
        previous = device_positions(physical, network)[command.operation.equipment]
        reason = None
        attempts += 1
        if override and override.fail:
            reason = "Scenario actuator failure"
        else:
            try:
                physical = change_position(physical, command.operation, network)
            except ValueError as exc:
                reason = str(exc)
        position = device_positions(physical, network)[command.operation.equipment]
        changes += int(previous != position)
        audit.append(
            {
                "command_id": command.id,
                "at_s": state.now_s,
                "equipment": command.operation.equipment,
                "closed": position,
                "changed": previous != position,
                "reason": reason,
            }
        )
        if not (override and override.drop_feedback):
            delay = override.feedback_delay_s if override else 0
            row = PositionFeedback(
                command_id=command.id,
                sequence=sequence,
                equipment=command.operation.equipment,
                closed=position,
                measured_at_s=state.now_s,
                due_s=state.now_s + delay,
            )
            feedback.append(row)
            for i in range(override.duplicates if override else 0):
                feedback.append(
                    row.model_copy(
                        update={"due_s": row.due_s + (i + 1) * override.duplicate_delay_s}
                    )
                )
        sequence += 1
    metrics = state.metrics.model_copy(
        update={
            "actuation_attempts": state.metrics.actuation_attempts + attempts,
            "position_changes": state.metrics.position_changes + changes,
        }
    )
    return state.model_copy(
        update={
            "physical": physical,
            "feedback": tuple(feedback),
            "actuations": tuple(r for r in state.actuations if r.due_s > state.now_s),
            "next_feedback_sequence": sequence,
            "metrics": metrics,
        }
    ), audit


def assert_compatible(state, engine):
    if (
        state.manifest["episode_sha256"] != episode_hash()
        or state.manifest["network_sha256"] != network_hash(engine.network)
        or state.manifest["solver_version"] != engine.version
    ):
        raise ValueError("Session requires its recorded source, model and OpenDSS version")


def controller_view(state):
    """Explicit allowed-information projection; no queue, actual demand or cause."""
    signals, estimates = observation_rows(
        state.telemetry, load_network(), state.now_s, state.config.measurements
    )
    return {
        "at_s": state.now_s,
        "remaining_horizon_s": state.config.horizon_s - state.now_s,
        "uncertainty_model": {
            "growth_pct_per_s": state.config.measurements.uncertainty_growth_pct_per_s,
            "maximum_pct": state.config.measurements.maximum_uncertainty_pct,
        },
        "signals": signals,
        "demand_estimates": estimates,
        "alarms": [
            r.model_dump(mode="json")
            for r in sorted(state.rules.alarms.values(), key=lambda r: r.id)
        ],
    }
