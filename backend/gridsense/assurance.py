"""Evaluation-only controller fault injection; never registered in the web API.

Mutations affect selection/status interpretation only. The native plant, action
guard, service contract and production controller implementations are untouched.
This is a trusted-code testing utility, not an untrusted-plugin sandbox.
"""

import copy
import hashlib
from importlib.resources import files

from .cases import PortableCase, ServiceContract
from .controllers import CONTROLLERS, RankedController
from .domain import Scenario
from .plants import plant_for, planning_view
from .regression import AT, checksum, evaluate_case, harness_hash
from .service import _differences
from .temporal import ExecutionTracker


VARIANTS = {
    "nominal-control": "nominal-v1",
    "guarded-control": "guarded-v1",
    "skip-feasibility": "nominal-v1",
    "reverse-service": "nominal-v1",
    "cached-action": "nominal-v1",
    "reverse-operations": "nominal-v1",
    "ignore-uncertainty": "guarded-v1",
}


class ExperimentalController:
    def __init__(self, name):
        if name not in VARIANTS:
            raise ValueError("Unknown experimental controller")
        self.id = name
        self.cached = None

    def select(self, view):
        reference = CONTROLLERS[VARIANTS[self.id]]
        if self.id == "cached-action":
            if self.cached is None:
                self.cached = reference.select(view)
            return self.cached
        if self.id == "ignore-uncertainty":
            return CONTROLLERS["nominal-v1"].select(view)
        if self.id in {"skip-feasibility", "reverse-service"}:
            candidates = [
                c for c in view.candidates if self.id == "skip-feasibility" or c.nominal.feasible
            ]
            if not candidates:
                return next(c.action for c in view.candidates if c.action.id == "hold")
            sign = 1 if self.id == "reverse-service" else -1
            return min(
                candidates,
                key=lambda c: (
                    sign * round(c.nominal.critical_served_kw, 1),
                    sign * round(c.nominal.served_kw, 1),
                    len(c.action.operations),
                    c.nominal.max_loading_pct,
                    c.action.id,
                ),
            ).action
        action = reference.select(view)
        if self.id == "reverse-operations":
            return action.model_copy(update={"operations": tuple(reversed(action.operations))})
        return action


class MeteredPlant:
    """Count completed adapter snapshots, not internal DSS iterations/contexts.

    Both existing adapters solve once per operation, or once for an empty action.
    Counting happens after unmodified execution. Exceptions propagate to the runner.
    """

    def __init__(self, plant):
        self.plant = plant
        self.adapter_solves = 0

    def __getattr__(self, name):
        return getattr(self.plant, name)

    def solve(self, state):
        result = self.plant.solve(state)
        self.adapter_solves += 1
        return result

    def execute(self, state, action):
        result = self.plant.execute(state, action)
        self.adapter_solves += max(1, len(result.steps))
        return result


def priming_case(case):
    if case.feeder == "teaching":
        scenario = Scenario(
            load_a=1, load_b=0.65, reported_b=0.65, load_c=1.1, telemetry_age_s=0, uncertainty_pct=0
        )
    else:
        scenario = Scenario(
            load_a=0.65,
            load_b=0.65,
            reported_b=0.65,
            load_c=1,
            telemetry_age_s=0,
            uncertainty_pct=0,
        )
    return PortableCase(
        title="Fixed priming observation",
        feeder=case.feeder,
        fault=case.fault,
        scenario=scenario,
        contract=ServiceContract(minimum_restored_kw=0, minimum_critical_kw=0),
        origin="Frozen assurance protocol; only observation is given to controller",
    )


def prepare_episode(case, prime=None, *, assess_attainability=False):
    """Shared prediction cost is recorded once; truth never enters PlanningView."""
    prime = prime or priming_case(case)
    first = MeteredPlant(plant_for(prime))
    prime_view = planning_view(first, AT)
    plant = MeteredPlant(plant_for(case))
    view = planning_view(plant, AT)
    costs = {
        "priming_prediction_solves": first.adapter_solves,
        "target_prediction_solves": plant.adapter_solves,
    }
    context = {
        "priming_case": prime,
        "prime_view": prime_view,
        "plant": plant,
        "view": view,
        "costs": costs,
    }
    if assess_attainability:
        before = plant.adapter_solves
        initial = plant.solve(plant.truth)
        alternatives = []
        for candidate in view.candidates:
            result = plant.execute(plant.truth, candidate.action).result
            service = (
                result.restored_kw + 0.1 >= case.contract.minimum_restored_kw
                and result.critical_served_kw + 0.1 >= case.contract.minimum_critical_kw
            )
            alternatives.append(
                {
                    "action": candidate.action.id,
                    "electrical_pass": result.feasible,
                    "service_pass": service,
                }
            )
        context["attainability"] = {
            "initial_electrical_pass": initial.feasible,
            "truth_attainable": any(
                r["electrical_pass"] and r["service_pass"] for r in alternatives
            ),
            "alternatives": alternatives,
        }
        costs["privileged_attainability_solves"] = plant.adapter_solves - before
    return context


def compact(outcome):
    result = outcome["result"]
    action_id = outcome["action"]["id"]
    prediction = next(c for c in outcome["predictions"] if c["action"]["id"] == action_id)
    return {
        "controller": outcome["controller"],
        "action": outcome["action"],
        "electrical_pass": outcome["electrical_pass"],
        "service_pass": outcome["service_pass"],
        "passed": outcome["passed"],
        "result": result,
        "selected_prediction": prediction,
        "observation": outcome["observation"],
        "steps": outcome["steps"],
    }


def classify(reference, candidate):
    """An adverse input is not itself evidence of a defect in the candidate."""
    if not reference["passed"]:
        return {"detected": False, "category": "reference-failed-inconclusive", "losses": []}
    if candidate.get("rejected"):
        return {"detected": True, "category": "action-interface-rejection", "losses": []}
    losses = [
        key
        for key in ("critical_served_kw", "restored_kw", "served_kw")
        if candidate["result"][key] + 0.1 < reference["result"][key]
    ]
    category = (
        "electrical-regression"
        if not candidate["electrical_pass"]
        else "service-contract-regression"
        if not candidate["service_pass"]
        else "service-loss"
        if losses
        else "no-regression"
    )
    return {"detected": category != "no-regression", "category": category, "losses": losses}


def compare_episode(case, variant, *, prepared=None, prime=None):
    prepared = prepared or prepare_episode(case, prime)
    reference_name = VARIANTS[variant]
    reference = RankedController(reference_name, guarded=reference_name == "guarded-v1")
    candidate = ExperimentalController(variant)
    # Each episode resets state. Both receive identical deep-copied priming input.
    priming_actions = [
        controller.select(copy.deepcopy(prepared["prime_view"])).model_dump(mode="json")
        for controller in (reference, candidate)
    ]
    plant, view = prepared["plant"], prepared["view"]
    before = plant.adapter_solves
    baseline = compact(evaluate_case(case, reference, plant=plant, view=view))
    try:
        outcome = compact(evaluate_case(case, candidate, plant=plant, view=view))
    except ValueError as exc:
        if "outside the advertised feasible action space" not in str(exc):
            raise  # A harness/solver failure must not masquerade as a detected mutation.
        outcome = {"controller": variant, "rejected": True, "reason": str(exc)}
    return {
        "variant": variant,
        "reference": baseline,
        "candidate": outcome,
        "priming_actions": priming_actions,
        **classify(baseline, outcome),
        "execution_adapter_solves": plant.adapter_solves - before,
        "solver_version": plant.version,
    }


def simplification_candidates(case, prime):
    """Finite, explicit changes, rebuilding Pydantic inputs to enforce invariants."""
    current, anchor = case.scenario.model_dump(), prime.scenario.model_dump()
    for field in ("load_a", "load_b", "load_c", "reported_b", "telemetry_age_s", "uncertainty_pct"):
        value = anchor[field]
        if current[field] == value:
            continue
        changed = dict(current)
        changed[field] = value
        if changed["telemetry_age_s"] == 0:
            # Do not create fresh-but-disagreeing measurement/truth combinations.
            if field in {"load_b", "reported_b"}:
                changed["load_b"] = changed["reported_b"] = value
                if case.feeder == "ieee13":
                    changed["load_a"] = value
            if case.feeder == "ieee13" and field == "load_a":
                changed["load_b"] = changed["reported_b"] = value
        try:
            yield PortableCase.model_validate({**case.model_dump(), "scenario": changed})
        except ValueError:
            continue


def complexity(case, prime):
    fields = ("load_a", "load_b", "load_c", "reported_b", "telemetry_age_s", "uncertainty_pct")
    return sum(getattr(case.scenario, k) != getattr(prime.scenario, k) for k in fields)


def reduce_episode(case, variant, budget=24):
    if not 0 <= budget <= 64:
        raise ValueError("Reduction budget must be between 0 and 64")
    prime = priming_case(case)
    original_prepared = prepare_episode(case, prime)
    original = compare_episode(case, variant, prepared=original_prepared)
    original_cost = sum(original_prepared["costs"].values()) + original["execution_adapter_solves"]
    if not original["detected"]:
        raise ValueError("Reduction requires an attributable detected regression")
    current, result = case, original
    trials, solves = [], 0
    while len(trials) < budget:
        changed = False
        for proposal in simplification_candidates(current, prime):
            if len(trials) >= budget:
                break
            if complexity(proposal, prime) >= complexity(current, prime):
                continue
            prepared = prepare_episode(proposal, prime)
            tested = compare_episode(proposal, variant, prepared=prepared)
            cost = sum(prepared["costs"].values()) + tested["execution_adapter_solves"]
            solves += cost
            kept = tested["detected"] and tested["category"] == original["category"]
            trials.append(
                {
                    "case": proposal.model_dump(mode="json"),
                    "kept": kept,
                    "category": tested["category"],
                    "adapter_solves": cost,
                }
            )
            if kept:
                current, result, changed = proposal, tested, True
                break
        if not changed:
            break
    record = {
        "kind": "controller-defect-reproducer",
        "schema_version": 1,
        "variant": variant,
        "original_case": case.model_dump(mode="json"),
        "reduced_case": current.model_dump(mode="json"),
        "priming_case": prime.model_dump(mode="json"),
        "original": original,
        "reduced": result,
        "trials": trials,
        "complexity_before": complexity(case, prime),
        "complexity_after": complexity(current, prime),
        "budget": budget,
        "cost": {
            "original_recheck_adapter_solves": original_cost,
            "reduction_adapter_solves": solves,
        },
        "manifest": {
            "assurance_sha256": assurance_hash(),
            "harness_sha256": harness_hash(),
            "solver_version": original["solver_version"],
        },
    }
    record["content_sha256"] = checksum(record)
    return record


def assurance_hash():
    return hashlib.sha256(
        harness_hash().encode() + files("gridsense").joinpath("assurance.py").read_bytes()
    ).hexdigest()


def replay_defect(record):
    if record.get("kind") != "controller-defect-reproducer" or checksum(record) != record.get(
        "content_sha256"
    ):
        raise ValueError("Defect reproducer integrity/type check failed")
    if (
        record["manifest"]["assurance_sha256"] != assurance_hash()
        or record["manifest"]["harness_sha256"] != harness_hash()
    ):
        raise ValueError("Strict defect replay requires the recorded implementation")
    differences, costs = [], 0
    prime = PortableCase.model_validate(record["priming_case"])
    for label in ("original", "reduced"):
        case = PortableCase.model_validate(record[label + "_case"])
        prepared = prepare_episode(case, prime)
        actual = compare_episode(case, record["variant"], prepared=prepared)
        if actual["solver_version"] != record["manifest"]["solver_version"]:
            raise ValueError("Strict defect replay requires the recorded OpenDSS version")
        differences.extend(_differences(record[label], actual, label, 1e-7))
        costs += sum(prepared["costs"].values()) + actual["execution_adapter_solves"]
    return {"matched": not differences, "differences": differences, "adapter_solves": costs}


def assess_temporal_trace(simulation, variant):
    """Feed public messages to a tracker; the checker alone reads native truth.

    The physical trace comes from the unchanged temporal simulator. No alternative
    actuator effects are generated here. A received position message exposes the
    physical position at that message time in this existing one-command model.
    """
    if variant not in {
        "confirmed-control",
        "optimistic-command",
        "timeout-success",
        "inverted-position",
    }:
        raise ValueError("Unknown temporal variant")
    tracker = ExecutionTracker(require_confirmation=variant != "optimistic-command")
    received_closed = False
    rows, failures = [], []
    for row in simulation["trace"]:
        event = row["event"]
        if event not in {"command", "position", "timeout"}:
            continue
        position = row["physical_closed"] if event == "position" else None
        if event == "position":
            received_closed = position
        tracker.receive(
            event,
            not position if variant == "inverted-position" and event == "position" else position,
        )
        if (
            variant == "timeout-success"
            and event == "timeout"
            and tracker.state.startswith("unknown")
        ):
            tracker.state = "restored"
        bad = (
            event in {"position", "timeout"}
            and tracker.state == "restored"
            and (
                not received_closed
                or row["actual_restored_kw"] + 0.1 < simulation["predicted_restored_kw"]
            )
        )
        entry = {
            "at_s": row["at_s"],
            "event": event,
            "status": tracker.state,
            "received_closed": received_closed,
            "actual_restored_kw": row["actual_restored_kw"],
            "violated": bad,
        }
        rows.append(entry)
        if bad:
            failures.append(entry)
    return {"variant": variant, "detected": bool(failures), "failures": failures, "messages": rows}
