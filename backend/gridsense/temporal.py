"""Bounded discrete-event actuator/confirmation experiment over native snapshots.

This is not electromagnetic transient simulation. Faulty and verified trackers
see the same command and delayed position feedback, never actuator truth.
"""

import heapq
import random
from dataclasses import dataclass
from typing import Literal
from uuid import uuid4
from pydantic import Field, model_validator
from .cases import PortableCase
from .controllers import CONTROLLERS
from .domain import Record, Scenario
from .plants import plant_for, planning_view
from .service import utc_now, _differences


class DeviceEvent(Record):
    kind: Literal["fail_close", "delay_confirmation", "heartbeat"]
    at_s: int = Field(default=0, ge=0, le=1)
    delay_s: int = Field(default=0, ge=0, le=20)

    @model_validator(mode="after")
    def meaningful_delay(self):
        if self.kind != "delay_confirmation" and self.delay_s:
            raise ValueError("Only a confirmation delay event may specify delay_s")
        return self


class TemporalInput(Record):
    seed: int = Field(default=42, ge=0, le=2**31 - 1)
    budget: int = Field(default=12, ge=1, le=32)
    reduction_budget: int = Field(default=24, ge=0, le=64)
    timeout_s: int = Field(default=5, ge=2, le=10)
    case: PortableCase = Field(
        default_factory=lambda: PortableCase(
            title="Failed tie closure with delayed position feedback",
            scenario=Scenario(
                load_b=0.7, reported_b=0.7, load_c=1.1, telemetry_age_s=0, uncertainty_pct=0
            ),
            origin="Temporal actuator experiment; optimistic tracker is a deliberately faulty baseline",
        )
    )


@dataclass
class ExecutionTracker:
    require_confirmation: bool
    state: str = "isolated"
    confirmed_closed: bool = False

    def receive(self, event: str, position: bool | None = None):
        if event == "command":
            self.state = "pending" if self.require_confirmation else "restored"
        elif event == "position":
            self.confirmed_closed = bool(position)
            self.state = "restored" if position else "failed"
        elif event == "timeout" and self.require_confirmation and self.state == "pending":
            self.state = "unknown — confirmation timeout"


def simulate_events(request: TemporalInput, events: list[DeviceEvent]) -> dict:
    plant = plant_for(request.case)
    view = planning_view(plant, "2026-01-01T12:00:00+00:00")
    action = CONTROLLERS["nominal-v1"].select(view)
    if len(action.operations) != 1 or not action.operations[0].closed:
        raise ValueError(
            "Temporal experiment requires one electrically selected tie-closing operation"
        )
    predicted = next(c.nominal for c in view.candidates if c.action == action)
    if not predicted.feasible or predicted.restored_kw <= 0:
        raise ValueError("Temporal experiment requires a predicted feasible restoration")
    trackers = {"optimistic-v1": ExecutionTracker(False), "confirmed-v2": ExecutionTracker(True)}
    state = plant.truth
    result = plant.solve(state)
    failed, delay, position = False, 0, False
    queue = [(e.at_s, 0, i, "environment", e) for i, e in enumerate(events)]
    queue += [
        (1, 1, 100, "command", None),
        (2, 2, 101, "actuate", None),
        (1 + request.timeout_s, 4, 102, "timeout", None),
    ]
    heapq.heapify(queue)
    trace = []
    failures = []
    unserved_kwh = 0.0
    previous_time = 0
    for_count = 0
    while queue:
        time, _, _, kind, event = heapq.heappop(queue)
        unserved_kwh += result.unserved_kw * (time - previous_time) / 3600
        previous_time = time
        detail = kind
        if kind == "environment":
            if event.kind == "fail_close":
                failed = True
            if event.kind == "delay_confirmation":
                delay = event.delay_s
            detail = event.kind
        elif kind == "command":
            for tracker in trackers.values():
                tracker.receive("command")
            detail = f"Requested close {action.operations[0].line}"
        elif kind == "actuate":
            if not failed:
                outcome = plant.execute(state, action)
                state = outcome.final_state
                result = outcome.result
                position = True
            # Failure keeps the real native circuit open; the tracker is not told.
            heapq.heappush(queue, (time + delay, 3, 103, "position", position))
            detail = "Actuator remained open" if failed else "Actuator closed"
        elif kind == "position":
            for tracker in trackers.values():
                tracker.receive("position", event)
            detail = f"Position feedback: {'closed' if event else 'open'}"
        elif kind == "timeout":
            for tracker in trackers.values():
                tracker.receive("timeout")
            for name, tracker in trackers.items():
                if tracker.state == "restored" and result.restored_kw + 0.1 < predicted.restored_kw:
                    failures.append(
                        {"controller": name, "kind": "false_restored_after_timeout", "at_s": time}
                    )
        trace.append(
            {
                "at_s": time,
                "event": kind,
                "detail": detail,
                "commanded_closed": time >= 1,
                "physical_closed": position,
                "trackers": {
                    name: {"status": t.state, "confirmed_closed": t.confirmed_closed}
                    for name, t in trackers.items()
                },
                "actual_restored_kw": result.restored_kw,
                "actual_unserved_kw": result.unserved_kw,
                "electrical_pass": result.feasible,
            }
        )
        for_count += 1
        if for_count > 64:
            raise ValueError("Event budget exceeded")
    return {
        "events": [e.model_dump() for e in events],
        "action": action.model_dump(mode="json"),
        "trace": trace,
        "failures": failures,
        "is_failure": any(f["controller"] == "optimistic-v1" for f in failures),
        "final_electrical": result.model_dump(mode="json"),
        "unserved_energy_kwh": unserved_kwh,
        "duration_s": previous_time,
        "predicted_restored_kw": predicted.restored_kw,
        "solver_version": plant.version,
        "interpretation": "The confirmed tracker can report unknown or failed without restoring service. Preventing a false success claim does not repair the switch or recover its load.",
    }


def event_complexity(events):
    return (len(events), sum(e.delay_s + e.at_s for e in events))


def reduce_events(request, original):
    events = [DeviceEvent.model_validate(e) for e in original["events"]]
    current = original
    trace = []
    seen = set()
    exhausted = False
    while len(trace) < request.reduction_budget:
        proposals = [events[:i] + events[i + 1 :] for i in range(len(events))]
        for i, e in enumerate(events):
            for delay in sorted({0, e.delay_s // 2, max(0, e.delay_s - 1)}):
                if delay < e.delay_s:
                    proposals.append(
                        events[:i] + [e.model_copy(update={"delay_s": delay})] + events[i + 1 :]
                    )
        accepted = False
        for proposal in proposals:
            key = tuple((e.kind, e.at_s, e.delay_s) for e in proposal)
            if key in seen or event_complexity(proposal) >= event_complexity(events):
                continue
            seen.add(key)
            result = simulate_events(request, proposal)
            preserve = result["is_failure"] and not any(
                f["controller"] == "confirmed-v2" for f in result["failures"]
            )
            trace.append({"events": [e.model_dump() for e in proposal], "accepted": preserve})
            if preserve:
                events = proposal
                current = result
                accepted = True
                break
            if len(trace) >= request.reduction_budget:
                break
        if not accepted:
            exhausted = len(trace) < request.reduction_budget
            break
    return current, {
        "evaluations": len(trace),
        "trace": trace,
        "neighborhood_exhausted": exhausted,
        "original_complexity": event_complexity(
            [DeviceEvent.model_validate(e) for e in original["events"]]
        ),
        "reduced_complexity": event_complexity(events),
        "minimality": "Greedy deletion/delay neighborhood only; no global minimum guarantee",
    }


def run_temporal(request: TemporalInput):
    from .regression import checksum, harness_hash

    rng = random.Random(request.seed)
    trials = []
    first = None
    for i in range(request.budget):
        events = [DeviceEvent(kind="delay_confirmation", delay_s=rng.randrange(21))]
        if rng.random() < 0.65:
            events.append(DeviceEvent(kind="fail_close"))
        if rng.random() < 0.7:
            events.append(DeviceEvent(kind="heartbeat", at_s=1))
        result = simulate_events(request, events)
        trials.append(
            {"evaluation": i + 1, "events": result["events"], "is_failure": result["is_failure"]}
        )
        if result["is_failure"] and first is None:
            first = result
    reduced, reduction = reduce_events(request, first) if first else (None, None)
    record = {
        "schema_version": 1,
        "kind": "temporal",
        "id": str(uuid4()),
        "created_at": utc_now(),
        "request": request.model_dump(mode="json"),
        "trials": trials,
        "original": first,
        "reduced": reduced,
        "reduction": reduction,
        "status": "failure_found" if first else "no_failure_found",
        "manifest": {
            "harness_sha256": harness_hash(),
            "solver_version": plant_for(request.case).version,
        },
        "limitations": [
            "Deliberately faulty optimistic tracker compared with confirmation-based state machine",
            "Discrete events with steady-state power flow, not relay, protection or transient dynamics",
            "One command; no retries, alternate switching or repair after an actuator failure",
            "No failure in a finite search does not establish correctness",
        ],
    }
    record["content_sha256"] = checksum(record)
    return record


def replay_temporal(record):
    from .regression import checksum, harness_hash

    if checksum(record) != record.get("content_sha256"):
        raise ValueError("Temporal export integrity check failed")
    if record["manifest"]["harness_sha256"] != harness_hash():
        raise ValueError("Historical temporal replay requires the recorded harness")
    request = TemporalInput.model_validate(record["request"])
    differences = []
    for key in ("original", "reduced"):
        if record[key] is None:
            continue
        actual = simulate_events(
            request, [DeviceEvent.model_validate(e) for e in record[key]["events"]]
        )
        if actual["solver_version"] != record["manifest"]["solver_version"]:
            raise ValueError("OpenDSS version mismatch")
        differences.extend(_differences(record[key], actual, key))
    if record["original"] is None:
        raise ValueError("No retained failure to replay")
    return {
        "matched": not differences,
        "differences": differences,
        "kind": "strict_temporal_replay",
    }
