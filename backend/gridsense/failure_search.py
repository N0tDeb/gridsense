"""Bounded search and greedy reduction of electrically avoidable violations.

The searcher is an evaluator with access to simulator truth. Controllers still
receive only the observations passed by service.evaluate. No policy is retrained.
"""

import hashlib
import itertools
import json
import random
from collections import Counter
from importlib.resources import files
from time import perf_counter
from typing import Literal
from uuid import uuid4

from pydantic import Field, model_validator
from .domain import Record, Scenario
from .service import _differences, evaluate, implementation_hash, replay, utc_now

VARIABLES = ("load_a", "load_b", "load_c", "reported_b")
GRID_STEP = 0.05
FIXED_AT = "2026-01-01T12:00:00+00:00"
TARGET = "avoidable_violation"


def tick(value: float) -> int:
    return round(value / GRID_STEP)


class Bounds(Record):
    minimum: float = Field(ge=0.5, le=2)
    maximum: float = Field(ge=0.5, le=2)

    @model_validator(mode="after")
    def on_grid(self):
        if self.minimum > self.maximum:
            raise ValueError("minimum must not exceed maximum")
        if any(abs(tick(v) * GRID_STEP - v) > 1e-9 for v in (self.minimum, self.maximum)):
            raise ValueError("Search bounds must lie on the 0.05 demand-factor grid")
        return self


class SearchInput(Record):
    policy: Literal["nominal", "guarded"] = "nominal"
    seed: int = Field(default=42, ge=0, le=2**31 - 1)
    budget: int = Field(default=24, ge=4, le=64)
    reduction_budget: int = Field(default=48, ge=0, le=96)
    uncertainty_pct: float = Field(default=40, ge=0, le=80)
    telemetry_age_s: int = Field(default=120, ge=1, le=3600)
    assumption_scope: Literal["inside", "unrestricted"] = "inside"
    bounds: dict[str, Bounds] = Field(
        default_factory=lambda: {
            "load_a": Bounds(minimum=0.75, maximum=1.25),
            "load_b": Bounds(minimum=0.5, maximum=2),
            "load_c": Bounds(minimum=0.5, maximum=1.8),
            "reported_b": Bounds(minimum=0.5, maximum=1.5),
        }
    )
    reference: dict[str, float] = Field(
        default_factory=lambda: {
            "load_a": 1,
            "load_b": 0.8,
            "load_c": 1,
            "reported_b": 0.8,
        }
    )

    @model_validator(mode="after")
    def valid_space(self):
        if set(self.bounds) != set(VARIABLES) or set(self.reference) != set(VARIABLES):
            raise ValueError("bounds and reference must contain exactly the four demand variables")
        if self.bounds["load_a"].maximum > 1.5:
            raise ValueError("Affected demand must not exceed 1.5")
        for name, bound in self.bounds.items():
            v = self.reference[name]
            if not bound.minimum <= v <= bound.maximum or abs(tick(v) * GRID_STEP - v) > 1e-9:
                raise ValueError(f"Reference {name} must be inside its bounds on the 0.05 grid")
        if self.assumption_scope == "inside" and not inside_assumption(
            self.reference, self.uncertainty_pct
        ):
            raise ValueError("Reference west demand must be inside the assumed uncertainty range")
        return self


def inside_assumption(point: dict, uncertainty_pct: float) -> bool:
    reported = point["reported_b"]
    delta = uncertainty_pct / 100
    return reported * (1 - delta) - 1e-9 <= point["load_b"] <= reported * (1 + delta) + 1e-9


def search_hash() -> str:
    return hashlib.sha256(
        implementation_hash().encode()
        + files("gridsense").joinpath("failure_search.py").read_bytes()
    ).hexdigest()


def content_hash(record: dict) -> str:
    data = {k: v for k, v in record.items() if k != "content_sha256"}
    return hashlib.sha256(
        json.dumps(data, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    ).hexdigest()


def scenario_for(request: SearchInput, point: dict) -> Scenario:
    return Scenario(
        title="Discovered restoration case",
        **point,
        policy=request.policy,
        telemetry_age_s=request.telemetry_age_s,
        uncertainty_pct=request.uncertainty_pct,
    )


def describe(incident: dict, policy: str) -> dict:
    """Physical avoidability is assessed with privileged information, after choice."""
    before = incident["before"]
    decision = incident["decisions"][policy]
    outcome = incident["outcomes"][policy]
    result = outcome["result"]
    reference = incident["outcomes"]["oracle"]
    restorable = reference["result"]["feasible"] and reference["result"]["critical_served_kw"] > 0.1
    if not before["converged"] or not result["converged"]:
        category = "solver_failure"
    elif not before["feasible"]:
        category = "pre_existing_violation"
    elif not restorable:
        category = "no_feasible_restoration"
    elif not decision["feasible_choice"] or outcome["action"]["id"] == "hold":
        category = "controller_deferred"
    elif not result["feasible"]:
        category = TARGET
    else:
        category = "within_limits"
    low, high = incident["manifest"]["network"]["voltage_limits_pu"]
    live = set(result["energized_buses"]) | {"source"}
    volts = [v for bus, v in result["voltages_pu"].items() if bus.removesuffix("_lv") in live]
    # Signed distance toward a constraint violation, not a probability of failure.
    margin = max(
        [
            result["max_loading_pct"] / 100 - 1,
            *[(low - v) / low for v in volts],
            *[(v - high) / high for v in volts],
        ]
    )
    score = margin if category in (TARGET, "within_limits") else -10.0
    violations = sorted(result["violations"], key=lambda v: (v["kind"], v["element"]))
    point = {name: incident["scenario"][name] for name in VARIABLES}
    return {
        "category": category,
        "is_failure": category == TARGET,
        "score": score,
        "action": outcome["action"]["id"],
        "action_label": outcome["action"]["label"],
        "truth_inside_assumed_range": inside_assumption(
            point, incident["scenario"]["uncertainty_pct"]
        ),
        "predicted_loading_pct": next(
            c["nominal"]["max_loading_pct"]
            for c in decision["candidates"]
            if c["action"]["id"] == outcome["action"]["id"]
        ),
        "actual_loading_pct": result["max_loading_pct"],
        "restored_kw": result["restored_kw"],
        "violations": violations,
        "feasible_alternative": {
            "action": reference["action"]["id"],
            "label": reference["action"]["label"],
            "feasible": reference["result"]["feasible"],
            "restored_kw": reference["result"]["restored_kw"],
            "critical_served_kw": reference["result"]["critical_served_kw"],
        },
    }


class SearchSpace:
    def __init__(self, request: SearchInput):
        self.request = request
        self.axes = [
            tuple(range(tick(request.bounds[k].minimum), tick(request.bounds[k].maximum) + 1))
            for k in VARIABLES
        ]
        self.west_pairs = [
            (b, r)
            for b in self.axes[1]
            for r in self.axes[3]
            if request.assumption_scope == "unrestricted"
            or inside_assumption(
                {"load_b": b * GRID_STEP, "reported_b": r * GRID_STEP}, request.uncertainty_pct
            )
        ]
        self.size = len(self.axes[0]) * len(self.axes[2]) * len(self.west_pairs)

    def admissible(self, point: tuple[int, ...]) -> bool:
        return (
            all(v in axis for v, axis in zip(point, self.axes))
            and (point[1], point[3]) in self.west_pairs
        )

    def random_point(self, rng: random.Random) -> tuple[int, ...]:
        b, reported = rng.choice(self.west_pairs)
        return rng.choice(self.axes[0]), b, rng.choice(self.axes[2]), reported

    def next_point(
        self, rng: random.Random, seen: set, best: tuple | None, directed: bool, index: int
    ) -> tuple | None:
        if len(seen) == self.size:
            return None
        # First four points match uniform search under the paired seed. Then
        # alternate local mutations (three trials) with global exploration (one).
        for attempt in range(100):
            if directed and best is not None and index >= 4 and index % 4 != 0 and attempt < 60:
                point = list(best)
                axis = rng.randrange(4)
                radius = max(1, len(self.axes[axis]) // 4)
                point[axis] += rng.choice((-1, 1)) * rng.randint(1, radius)
                candidate = tuple(point)
            else:
                candidate = self.random_point(rng)
            if candidate not in seen and self.admissible(candidate):
                return candidate
        # Finite deterministic fallback for a nearly exhausted small space.
        return next(
            (p for p in itertools.product(*self.axes) if p not in seen and self.admissible(p)), None
        )


def as_point(ticks: tuple) -> dict:
    return {name: round(value * GRID_STEP, 2) for name, value in zip(VARIABLES, ticks)}


def discover(
    request: SearchInput, strategy: Literal["directed", "random"], at: str = FIXED_AT
) -> tuple[dict, dict | None]:
    if strategy not in ("directed", "random"):
        raise ValueError("Unknown search strategy")
    space = SearchSpace(request)
    rng = random.Random(request.seed)
    seen, trace = set(), []
    best, best_score, first = None, float("-inf"), None
    first_index, first_seconds = None, None
    start = perf_counter()
    for i in range(request.budget):
        ticks = space.next_point(rng, seen, best, strategy == "directed", i)
        if ticks is None:
            break
        seen.add(ticks)
        point = as_point(ticks)
        incident = evaluate(scenario_for(request, point), at)
        finding = describe(incident, request.policy)
        trace.append({"evaluation": i + 1, "point": point, **finding})
        if finding["score"] > best_score:
            best, best_score = ticks, finding["score"]
        if finding["is_failure"] and first is None:
            first, first_index, first_seconds = incident, i + 1, perf_counter() - start
    return {
        "strategy": strategy,
        "evaluations": len(trace),
        "budget": request.budget,
        "space_exhausted": len(seen) == space.size,
        "space_size": space.size,
        "first_failure_evaluation": first_index,
        "seconds_to_first_failure": first_seconds,
        "elapsed_seconds": perf_counter() - start,
        "failing_scenarios": sum(row["is_failure"] for row in trace),
        "categories": dict(Counter(row["category"] for row in trace)),
        "trace": trace,
    }, first


def signature(finding: dict) -> dict:
    if not finding["is_failure"]:
        raise ValueError("Case does not meet the avoidable-violation target")
    primary = finding["violations"][0]
    return {
        "action": finding["action"],
        "kind": primary["kind"],
        "element": primary["element"],
        "truth_inside_assumed_range": finding["truth_inside_assumed_range"],
    }


def preserves(finding: dict, target: dict) -> bool:
    return (
        finding["is_failure"]
        and finding["action"] == target["action"]
        and finding["truth_inside_assumed_range"] == target["truth_inside_assumed_range"]
        and any(
            v["kind"] == target["kind"] and v["element"] == target["element"]
            for v in finding["violations"]
        )
    )


def complexity(point: dict, reference: dict) -> tuple[int, int]:
    differences = [abs(tick(point[k]) - tick(reference[k])) for k in VARIABLES]
    return sum(v != 0 for v in differences), sum(differences)


def simpler_neighbors(point: tuple, reference: tuple):
    seen = set()
    for axis, (value, target) in enumerate(zip(point, reference)):
        if value == target:
            continue
        direction = 1 if target > value else -1
        for replacement in (
            target,
            value + direction * (abs(target - value) // 2),
            value + direction,
        ):
            neighbor = list(point)
            neighbor[axis] = replacement
            candidate = tuple(neighbor)
            if candidate != point and candidate not in seen:
                seen.add(candidate)
                yield candidate


def reduce_case(request: SearchInput, original: dict) -> tuple[dict, dict]:
    finding = describe(original, request.policy)
    target = signature(finding)
    space = SearchSpace(request)
    point = {name: original["scenario"][name] for name in VARIABLES}
    current = tuple(tick(point[k]) for k in VARIABLES)
    if not space.admissible(current):
        raise ValueError("Original case is outside the requested search space")
    reference = tuple(tick(request.reference[k]) for k in VARIABLES)
    reduced = original
    trace, checks = [], 0
    exhausted = False
    # Reset, midpoint and one-grid-step moves; every accepted move is re-solved.
    # This does not assume monotonicity and does not claim a global minimum.
    while checks < request.reduction_budget:
        improved = False
        for candidate in simpler_neighbors(current, reference):
            if not space.admissible(candidate):
                continue
            if checks >= request.reduction_budget:
                break
            incident = evaluate(scenario_for(request, as_point(candidate)), original["created_at"])
            candidate_finding = describe(incident, request.policy)
            accepted = preserves(candidate_finding, target)
            checks += 1
            trace.append(
                {
                    "evaluation": checks,
                    "point": as_point(candidate),
                    "accepted": accepted,
                    "category": candidate_finding["category"],
                    "action": candidate_finding["action"],
                    "complexity": list(complexity(as_point(candidate), request.reference)),
                }
            )
            if accepted:
                current, reduced, improved = candidate, incident, True
                break
        else:
            if not improved:
                exhausted = True
                break
        if not improved:
            break
    return {
        "evaluations": checks,
        "budget": request.reduction_budget,
        "signature": target,
        "original_complexity": list(complexity(point, request.reference)),
        "reduced_complexity": list(complexity(as_point(current), request.reference)),
        "neighborhood_exhausted": exhausted,
        "trace": trace,
        "method": "Greedy coordinate resets, midpoints and 0.05 steps toward the declared reference; preserve action, primary violated constraint and assumption status. No global minimality claim.",
    }, reduced


def run_search(request: SearchInput) -> dict:
    at = utc_now()
    results, originals = {}, {}
    # Alternate execution order across seeds to reduce systematic warm-up bias.
    order = ("directed", "random") if request.seed % 2 == 0 else ("random", "directed")
    for method in order:
        results[method], originals[method] = discover(request, method, at)
    selected = (
        "directed"
        if originals["directed"] is not None
        else "random"
        if originals["random"] is not None
        else None
    )
    original = originals[selected] if selected else None
    reduction, reduced = reduce_case(request, original) if original else (None, None)
    record = {
        "schema_version": 1,
        "id": str(uuid4()),
        "created_at": at,
        "request": request.model_dump(),
        "search_implementation_sha256": search_hash(),
        "core_implementation_sha256": implementation_hash(),
        "status": "failure_found" if original else "no_failure_found",
        "selected_strategy": selected,
        "strategies": results,
        "reduction": reduction,
        "original_incident": original,
        "reduced_incident": reduced,
        "original_finding": describe(original, request.policy) if original else None,
        "reduced_finding": describe(reduced, request.policy) if reduced else None,
        "interpretation": "Avoidable means a feasible critical-serving alternative exists with privileged true demand. It does not mean the available telemetry uniquely identifies it. Failure counts are sampled scenarios, not independent bugs or deployment risk. No failure found is not a safety proof.",
        "comparison": "Equal budgets of complete incident evaluations, paired seed, same discrete admissible domain. Reduction and replay are excluded from discovery costs. The first directed failure is reduced, or the first random failure if directed finds none.",
    }
    record["content_sha256"] = content_hash(record)
    return record


def replay_search(record: dict) -> dict:
    if record.get("content_sha256") != content_hash(record):
        raise ValueError("Failure-search record failed its integrity check")
    if record["search_implementation_sha256"] != search_hash():
        raise ValueError("Failure-search implementation differs from the recorded version")
    if record["status"] != "failure_found":
        raise ValueError("This search did not find a failure to replay")
    request = SearchInput.model_validate(record["request"])
    differences, branches = [], {}
    for label in ("original", "reduced"):
        incident = record[f"{label}_incident"]
        result = replay(incident)
        differences.extend(f"{label}.{p}" for p in result["differences"])
        # Also rerun the controller: incident replay alone checks recorded actions.
        fresh = evaluate(Scenario.model_validate(incident["scenario"]), incident["created_at"])
        for key in ("observation", "decisions", "outcomes", "initial_state"):
            differences.extend(_differences(incident[key], fresh[key], f"{label}.{key}"))
        actual_finding = describe(fresh, request.policy)
        differences.extend(
            _differences(record[f"{label}_finding"], actual_finding, f"{label}.finding")
        )
        if not preserves(actual_finding, record["reduction"]["signature"]):
            differences.append(f"{label}: failure signature not reproduced")
        branches[label] = {
            "incident_id": incident["id"],
            "branches_checked": len(result["alternatives"]),
            "category": actual_finding["category"],
        }
    return {
        "search_id": record["id"],
        "matched": not differences,
        "differences": differences,
        "cases": branches,
        "checked_at": utc_now(),
        "tolerance": 1e-7,
        "method": "Replayed recorded electrical branches and reran controller decisions for original and reduced cases.",
    }
