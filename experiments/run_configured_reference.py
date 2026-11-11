"""Run the versioned constant-PQ profile against the unchanged 56 reference targets."""

import argparse
import hashlib
import json
from pathlib import Path

from gridsense.configured_reference import (
    PROTOCOL_SHA256,
    reference_rows,
    validate_configured_reference,
)
from gridsense.reference_checks import validate_extended_reference
from gridsense.service import _differences, utc_now

ROOT = Path(__file__).resolve().parents[1]
PROFILE = "experiments/protocols/constant_pq_reference_v1.json"
PROFILE_SHA256 = "b4bd606fa740bb62a0e0c95e68616a7acd5687e405c82514b11ada8a7a4df6c1"
PROTOCOL = "experiments/protocols/electrical.json"
INPUTS = (
    PROFILE,
    PROTOCOL,
    "experiments/run_configured_reference.py",
    "backend/gridsense/configured_reference.py",
    "backend/gridsense/reference_checks.py",
    "backend/gridsense/ieee13.py",
    "backend/gridsense/service.py",
    "backend/gridsense/circuits/ieee13/model.dss",
    "backend/gridsense/circuits/ieee13/reference.json",
)
BASELINE_FAILURES = {
    "load-current-675b",
    "load-kw-675b",
    "load-kvar-675b",
    "power-balance-kW",
}


def input_hashes():
    return {name: hashlib.sha256((ROOT / name).read_bytes()).hexdigest() for name in INPUTS}


def run_reference():
    before = input_hashes()
    if before[PROFILE] != PROFILE_SHA256 or before[PROTOCOL] != PROTOCOL_SHA256:
        raise ValueError("Versioned profile or frozen electrical targets changed")
    profile = json.loads((ROOT / PROFILE).read_text(encoding="utf-8"))
    protocol = json.loads((ROOT / PROTOCOL).read_text(encoding="utf-8"))
    baseline = validate_extended_reference(protocol)
    baseline_rows = reference_rows(baseline)
    result = validate_configured_reference(profile, protocol)
    result["native_default_baseline"] = {
        "configuration": "native-defaults",
        "passed": baseline["passed"],
        "converged": baseline["converged"],
        "passed_checks": sum(row["passed"] for row in baseline_rows),
        "total_checks": len(baseline_rows),
        "failed_checks": [row["id"] for row in baseline_rows if not row["passed"]],
        "checks": baseline_rows,
        "solver_version": baseline["solver_version"],
    }
    result["native_default_baseline_matched"] = (
        baseline["converged"]
        and not baseline["passed"]
        and len(baseline_rows) == 56
        and set(result["native_default_baseline"]["failed_checks"]) == BASELINE_FAILURES
    )
    result["passed"] = result["passed"] and result["native_default_baseline_matched"]
    if input_hashes() != before:
        raise ValueError("Reference inputs changed during execution")
    result.update({"verified_at": utc_now(), "inputs_sha256": before})
    return result


def require_finite_json(report):
    try:
        json.dumps(report, allow_nan=False)
    except (ValueError, TypeError) as exc:
        raise ValueError(
            "Configured reference contains non-finite or unsupported JSON data"
        ) from exc


def compare_reports(saved, actual):
    require_finite_json(saved)
    require_finite_json(actual)
    # Only the execution time may vary. Solver identity, configuration, inputs,
    # every expected/actual/tolerance value and both counts are compared.
    saved = {key: value for key, value in saved.items() if key != "verified_at"}
    actual = {key: value for key, value in actual.items() if key != "verified_at"}
    if _differences(saved, actual, "configured_reference", 1e-7):
        raise ValueError("Saved configured reference differs from actual native execution")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--verify-report", type=Path)
    args = parser.parse_args()
    if args.output and args.output.exists():
        parser.error("Output already exists; choose a new filename")
    try:
        saved = None
        if args.verify_report:
            saved = json.loads(args.verify_report.read_text(encoding="utf-8-sig"))
            if not isinstance(saved, dict):
                raise ValueError("Expected a configured reference JSON object")
            require_finite_json(saved)
        result = run_reference()
        if saved is not None:
            compare_reports(saved, result)
    except (OSError, KeyError, TypeError, ValueError) as exc:
        parser.error(str(exc))
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(
            json.dumps(result, indent=2, allow_nan=False) + "\n", encoding="utf-8"
        )
    print(
        json.dumps(
            {
                key: result[key]
                for key in (
                    "configuration",
                    "passed",
                    "passed_checks",
                    "total_checks",
                    "failed_checks",
                    "native_default_baseline_matched",
                )
            },
            indent=2,
        )
    )
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
