"""Incident orchestration: observations → planner → hidden-truth evaluation."""

import hashlib
import math
from datetime import datetime, timedelta, timezone
from importlib.resources import files
from uuid import uuid4
from . import __version__
from .domain import Action, CircuitState, Observation, Scenario, SweepInput
from .electrical import ElectricalEngine
from .network import initial_state, load_network, network_hash, restoration_baseline_kw
from .planning import choose_action
from .storage import IncidentStore


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def implementation_hash() -> str:
    # Replay refuses a different implementation instead of silently comparing
    # numbers from incompatible solver adapters or policy code.
    return hashlib.sha256(
        b"".join(
            files("gridsense").joinpath(name).read_bytes()
            for name in ("domain.py", "electrical.py", "network.py", "planning.py", "service.py")
        )
    ).hexdigest()


def observations(scenario: Scenario, at: str, network: dict) -> Observation:
    measurement_at = (
        datetime.fromisoformat(at) - timedelta(seconds=scenario.telemetry_age_s)
    ).isoformat()
    factors = {"a": scenario.load_a, "b": scenario.reported_b, "c": scenario.load_c}
    rows = []
    for load in network["loads"]:
        stale = load["feeder"] == "b" and scenario.telemetry_age_s > 0
        rows.append(
            {
                "sensor_id": f"meter_{load['id']}",
                "load_id": load["id"],
                "measurement": "active_demand_kw",
                "value": load["kw"] * factors[load["feeder"]],
                "unit": "kW",
                "measurement_at": measurement_at if stale else at,
                "received_at": at,
                "age_s": scenario.telemetry_age_s if stale else 0,
                "quality": "stale" if stale else "current",
                "source": "scenario demand telemetry; simulated, not a field measurement",
            }
        )
    return Observation(
        recorded_at=at,
        measurement_at=measurement_at,
        age_s=scenario.telemetry_age_s,
        load_factors=factors,
        uncertainty_pct=scenario.uncertainty_pct,
        rows=rows,
    )


def evaluate(scenario: Scenario, at: str | None = None) -> dict:
    at = at or utc_now()
    network = load_network()
    truth = initial_state(
        {"a": scenario.load_a, "b": scenario.load_b, "c": scenario.load_c}, network
    )
    observed = observations(scenario, at, network)
    # Deliberately erase true demand before invoking either real controller.
    controller_state = truth.model_copy(update={"load_factors": dict(observed.load_factors)})
    nominal = choose_action(observed, controller_state, "nominal", network)
    guarded = choose_action(observed, controller_state, "guarded", network)
    oracle_observed = observed.model_copy(
        update={
            "load_factors": dict(truth.load_factors),
            "age_s": 0,
            "uncertainty_pct": 0,
            "rows": [],
        }
    )
    oracle = choose_action(oracle_observed, truth, "oracle", network)
    decisions = {d.policy: d for d in (nominal, guarded, oracle)}
    engine = ElectricalEngine(
        network, restoration_baseline_kw=restoration_baseline_kw(truth, network)
    )
    before = engine.solve(truth)
    alternatives = []
    for candidate in nominal.candidates:
        outcome = engine.execute(truth, candidate.action)
        alternatives.append(outcome.model_dump(mode="json"))
    outcomes = {}
    for key, decision in decisions.items():
        outcomes[key] = next(
            a for a in alternatives if a["action"]["id"] == decision.selected_action.id
        )
    selected = decisions[scenario.policy]
    result = outcomes[scenario.policy]["result"]
    timeline = [
        {
            "step": 1,
            "event": "Section isolated",
            "detail": "feed_a opened at both terminals. Fault location is supplied; protection dynamics are outside this experiment.",
        },
        {
            "step": 2,
            "event": "Measurements recorded",
            "detail": f"West telemetry is {scenario.telemetry_age_s} seconds old. Other demand inputs are current.",
        },
        {
            "step": 3,
            "event": "Alternatives evaluated",
            "detail": f"{len(alternatives)} action sequences checked using observed demand and the declared policy.",
        },
        {
            "step": 4,
            "event": "Decision applied in OpenDSS",
            "detail": selected.selected_action.label,
        },
        {
            "step": 5,
            "event": "Electrical outcome evaluated",
            "detail": f"{result['restored_kw']:.0f} kW restored; {'modeled limits satisfied' if result['feasible'] else 'electrical constraint violation'}. Physical fault remains isolated.",
        },
    ]
    return {
        "schema_version": 1,
        "id": str(uuid4()),
        "created_at": at,
        "scenario": scenario.model_dump(),
        "manifest": {
            "app_version": __version__,
            "implementation_sha256": implementation_hash(),
            "network_sha256": network_hash(network),
            "network": network,
            "solver_version": engine.version,
            "simulation_mode": "deterministic balanced steady-state; no stochastic draws or dynamic controls",
        },
        "initial_state": truth.model_dump(mode="json"),
        "observation": observed.model_dump(mode="json"),
        "before": before.model_dump(mode="json"),
        "decisions": {k: d.model_dump(mode="json") for k, d in decisions.items()},
        "outcomes": outcomes,
        "alternatives": alternatives,
        "timeline": timeline,
        "limits": [
            "Synthetic teaching feeder; no utility validation.",
            "Finite uncertainty samples do not certify a continuous interval.",
            "Only one known isolated section and bounded switching alternatives are modeled.",
            "No transient stability, protection coordination, repair time, or communication protocol model.",
        ],
    }


def create_incident(scenario: Scenario, store: IncidentStore) -> dict:
    incident = evaluate(scenario)
    store.save(incident)
    return incident


def _differences(left, right, path="", tolerance=1e-7) -> list[str]:
    if isinstance(left, dict) and isinstance(right, dict):
        if left.keys() != right.keys():
            return [f"{path}: keys differ"]
        return [p for k in left for p in _differences(left[k], right[k], f"{path}.{k}", tolerance)]
    if isinstance(left, (list, tuple)) and isinstance(right, (list, tuple)):
        if len(left) != len(right):
            return [f"{path}: length differs"]
        return [
            p
            for i, (a, b) in enumerate(zip(left, right))
            for p in _differences(a, b, f"{path}[{i}]", tolerance)
        ]
    if isinstance(left, bool) or isinstance(right, bool):
        return [] if type(left) is bool and type(right) is bool and left == right else [path]
    if isinstance(left, (int, float)) and isinstance(right, (int, float)):
        # Reject non-finite data on either side, including equal infinities.
        # Otherwise inf <= tolerance * inf can admit a corrupted measurement.
        if any(isinstance(value, float) and not math.isfinite(value) for value in (left, right)):
            return [path]
        if left == right:
            return []
        try:
            return [] if abs(left - right) <= tolerance * max(1, abs(left), abs(right)) else [path]
        except OverflowError:
            # A malformed huge integer must not crash comparison with native floats.
            return [path]
    return [] if left == right else [path]


def replay(incident: dict) -> dict:
    manifest = incident["manifest"]
    if manifest["implementation_sha256"] != implementation_hash():
        raise ValueError(
            "Replay implementation differs from the recorded version. Use the original source snapshot."
        )
    if manifest["network_sha256"] != network_hash(manifest["network"]):
        raise ValueError("Recorded circuit definition failed its integrity check")
    initial = CircuitState.model_validate(incident["initial_state"])
    baseline = restoration_baseline_kw(initial, manifest["network"])
    engine = ElectricalEngine(manifest["network"], restoration_baseline_kw=baseline)
    if manifest["solver_version"] != engine.version:
        raise ValueError("Solver version differs from the recorded incident")
    differences = _differences(
        incident["before"], engine.solve(initial).model_dump(mode="json"), "before"
    )
    branches = []
    for original in incident["alternatives"]:
        # Reapply the recorded action, never replace it with today's policy choice.
        action = Action.model_validate(original["action"])
        outcome = (
            ElectricalEngine(manifest["network"], restoration_baseline_kw=baseline)
            .execute(initial, action)
            .model_dump(mode="json")
        )
        differences.extend(_differences(original, outcome, f"alternative.{action.id}"))
        branches.append(outcome)
    return {
        "incident_id": incident["id"],
        "matched": not differences,
        "tolerance": 1e-7,
        "differences": differences,
        "alternatives": branches,
        "checked_at": utc_now(),
        "method": "Reconstructed recorded circuit and loads; reapplied every recorded switching sequence in independent DSS contexts.",
    }


def sweep(request: SweepInput, store: IncidentStore | None = None) -> dict:
    rows = []
    at = utc_now()
    # Both controllers get exactly the same fixed observations at every point.
    # Only evaluator truth changes. Oracle is separately identified.
    for i in range(request.points):
        factor = request.minimum + (request.maximum - request.minimum) * i / (request.points - 1)
        scenario = Scenario.model_validate({**request.base.model_dump(), "load_b": factor})
        incident = evaluate(scenario, at)
        for policy, outcome in incident["outcomes"].items():
            result = outcome["result"]
            rows.append(
                {
                    "west_load_factor": factor,
                    "west_demand_kw": 700 * factor,
                    "policy": policy,
                    "action": outcome["action"]["id"],
                    "feasible": result["feasible"],
                    "restored_kw": result["restored_kw"],
                    "critical_served_kw": result["critical_served_kw"],
                    "unserved_kw": result["unserved_kw"],
                    "max_loading_pct": result["max_loading_pct"],
                    "min_voltage_pu": result["min_voltage_pu"],
                    "switch_count": len(outcome["action"]["operations"]),
                    "violations": "; ".join(v["message"] for v in result["violations"]),
                }
            )
    result = {
        "id": str(uuid4()),
        "created_at": at,
        "request": request.model_dump(),
        "rows": rows,
        "manifest": incident["manifest"],
        "interpretation": "Fixed west telemetry, varying actual west demand. Samples locate observed failures, not a certified boundary. Oracle has privileged true-demand information.",
    }
    if store:
        store.save_sweep(result)
    return result
