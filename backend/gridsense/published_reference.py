"""Corrected Official Results targets, separate from frozen legacy experiments."""

import hashlib
import json
import math
from importlib.resources import files

from .ieee13 import ROOT, context, phase_voltages


CONFIGURATION = "ieee13-published-official-reference-v2"
REFERENCE = files("gridsense").joinpath("references/ieee13_published_v2.json")
REFERENCE_SHA256 = "e6fabc296865712c1d419d64aa746b78fecb19fd2e05adb1bb31fb5d9f203905"


def validate_published_reference():
    raw = REFERENCE.read_bytes()
    if hashlib.sha256(raw).hexdigest() != REFERENCE_SHA256:
        raise ValueError("Published reference v2 dataset fingerprint changed")
    reference = json.loads(raw)
    model_hash = hashlib.sha256(ROOT.joinpath("model.dss").read_bytes()).hexdigest()
    if model_hash != reference["model_sha256"]:
        raise ValueError("Published reference v2 native model fingerprint changed")

    ctx = context()
    ctx.Solution.Solve()
    actual = phase_voltages(ctx)
    if any(not math.isfinite(actual[node]) for node in reference["voltages_pu"]):
        raise ValueError("Native reference voltages must be finite")
    rows = [
        {
            "node": node,
            "published_pu": target,
            "actual_pu": actual[node],
            "error_pu": abs(actual[node] - target),
            "passed": abs(actual[node] - target) <= reference["tolerance_pu"],
        }
        for node, target in reference["voltages_pu"].items()
    ]
    return {
        "feeder": "IEEE 13-node electrical reference (no restoration ties)",
        "configuration": CONFIGURATION,
        "reference_sha256": REFERENCE_SHA256,
        "model_sha256": model_hash,
        "converged": bool(ctx.Solution.Converged()),
        "passed": bool(ctx.Solution.Converged()) and all(row["passed"] for row in rows),
        "max_error_pu": max(row["error_pu"] for row in rows),
        "rows": rows,
        "tolerance_pu": reference["tolerance_pu"],
        "reference": reference["source"],
        "corrections": reference["corrections"],
        "solver_version": ctx.Basic.Version(),
        "scope": "Voltage magnitude agreement against the published Official Results column. Native default load windows and convergence settings are retained. Not validation of experimental ties, ampacities, protection, or restoration policy.",
    }
