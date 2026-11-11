"""Re-evaluation on current code is deliberately separate from strict replay."""

import copy
import hashlib
import json
from importlib.resources import files
from uuid import uuid4
from .cases import PortableCase, RegressionInput
from .controllers import Controller, CONTROLLERS
from .plants import plant_for, planning_view
from .service import implementation_hash, utc_now, _differences

AT = "2026-01-01T12:00:00+00:00"


def harness_hash():
    root = files("gridsense")
    names = ["cases.py", "controllers.py", "plants.py", "regression.py", "ieee13.py", "temporal.py"]
    content = implementation_hash().encode()
    for name in names:
        path = root.joinpath(name)
        content += name.encode() + path.read_bytes()
    for path in sorted(root.joinpath("circuits/ieee13").iterdir(), key=lambda p: p.name):
        if path.is_file():
            content += path.name.encode() + path.read_bytes()
    return hashlib.sha256(content).hexdigest()


def checksum(value):
    return hashlib.sha256(
        json.dumps(
            {k: v for k, v in value.items() if k != "content_sha256"},
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode()
    ).hexdigest()


def evaluate_case(case: PortableCase, controller: Controller, *, plant=None, view=None) -> dict:
    plant = plant or plant_for(case)
    view = copy.deepcopy(view or planning_view(plant, AT))
    action = controller.select(view)
    # Reject action IDs with changed operations, fault closure, and invented plans.
    allowed = {c.action.id: c.action for c in view.candidates}
    if action.id not in allowed or action != allowed[action.id]:
        raise ValueError(
            "Controller returned an action outside the advertised feasible action space"
        )
    outcome = plant.execute(plant.truth, action)
    result = outcome.result
    safety = result.feasible
    service = (
        result.restored_kw + 0.1 >= case.contract.minimum_restored_kw
        and result.critical_served_kw + 0.1 >= case.contract.minimum_critical_kw
    )
    return {
        "controller": controller.id,
        "action": action.model_dump(mode="json"),
        "electrical_pass": safety,
        "service_pass": service,
        "passed": safety and service,
        "result": result.model_dump(mode="json"),
        "steps": [r.model_dump(mode="json") for r in outcome.steps],
        "observation": view.observation.model_dump(mode="json"),
        "predictions": [c.model_dump(mode="json") for c in view.candidates],
    }


def run_regression(request: RegressionInput, historical_baseline: dict | None = None) -> dict:
    plant = plant_for(request.case)
    view = planning_view(plant, AT)
    baseline = (
        copy.deepcopy(historical_baseline["result"])
        if historical_baseline
        else evaluate_case(request.case, CONTROLLERS[request.baseline], plant=plant, view=view)
    )
    candidate = evaluate_case(request.case, CONTROLLERS[request.candidate], plant=plant, view=view)
    losses = []
    if baseline["electrical_pass"] and not candidate["electrical_pass"]:
        losses.append("New electrical violation")
    for key in ("critical_served_kw", "restored_kw", "served_kw"):
        if candidate["result"][key] + 0.1 < baseline["result"][key]:
            losses.append(f"Lower {key}")
    record = {
        "schema_version": 1,
        "kind": "regression",
        "id": str(uuid4()),
        "created_at": utc_now(),
        "request": request.model_dump(mode="json"),
        "baseline": baseline,
        "candidate": candidate,
        "historical_baseline": historical_baseline,
        "regressions": losses,
        "accepted": candidate["passed"] and not losses,
        "manifest": {
            "harness_sha256": harness_hash(),
            "solver_version": plant.version,
            "legacy_implementation_sha256": implementation_hash(),
        },
        "interpretation": "Current-code evaluation of a portable case. Acceptance requires the explicit electrical/service contract and no measured service regression. This is not historical replay or a proof over unseen cases.",
    }
    record["content_sha256"] = checksum(record)
    return record


def rerun_regression(previous: dict, candidate: str) -> dict:
    """Intentionally accept older source versions as INPUT, not as replay."""
    if checksum(previous) != previous.get("content_sha256"):
        raise ValueError("Previous regression export integrity check failed")
    request = RegressionInput.model_validate({**previous["request"], "candidate": candidate})
    history = {
        "source_record_id": previous["id"],
        "source_sha256": previous["content_sha256"],
        "source_manifest": previous["manifest"],
        "result": previous["candidate"],
    }
    return run_regression(request, history)


def replay_regression(record: dict) -> dict:
    if checksum(record) != record.get("content_sha256"):
        raise ValueError("Regression export integrity check failed")
    if record["manifest"]["harness_sha256"] != harness_hash():
        raise ValueError(
            "Historical replay requires the recorded harness. Use regress --file for intentional current-code evaluation."
        )
    actual = run_regression(
        RegressionInput.model_validate(record["request"]), record.get("historical_baseline")
    )
    if actual["manifest"]["solver_version"] != record["manifest"]["solver_version"]:
        raise ValueError("Historical replay requires the recorded OpenDSS version")
    differences = []
    for key in ("baseline", "candidate", "regressions", "accepted"):
        differences.extend(_differences(record[key], actual[key], key, 1e-7))
    return {
        "matched": not differences,
        "differences": differences,
        "kind": "strict_regression_replay",
    }
