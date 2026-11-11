"""Post-hoc reference-setting controls; keep native-default failures explicit.

Runs the same 56 frozen targets in four isolated native configurations. The
changed load window belongs to diagnostic contexts, not the simulation model.
"""

import argparse
import hashlib
import json
import multiprocessing
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path
from unittest.mock import patch

from gridsense import ieee13, reference_checks
from gridsense.service import _differences, utc_now

ROOT = Path(__file__).resolve().parents[1]
PROTOCOL = ROOT / "experiments/protocols/electrical.json"
PROTOCOL_SHA256 = "7648402dcbfc3b61ff183d2448922ec437bc9c08c02e838ee4796b3334267774"
CONFIGURATIONS = (
    ("native-defaults", None, None),
    ("precision-only", None, 1e-8),
    ("pq-envelope-only", 1.1, None),
    ("combined", 1.1, 1e-8),
)
MODEL_FAILURES = {"load-current-675b", "load-kw-675b", "load-kvar-675b"}


def input_hashes():
    names = (
        "experiments/run_reference_sensitivity.py",
        "experiments/protocols/electrical.json",
        "backend/gridsense/ieee13.py",
        "backend/gridsense/reference_checks.py",
        "backend/gridsense/service.py",
        "backend/gridsense/circuits/ieee13/model.dss",
        "backend/gridsense/circuits/ieee13/reference.json",
    )
    return {name: hashlib.sha256((ROOT / name).read_bytes()).hexdigest() for name in names}


def evaluate_configuration(configuration, protocol):
    name, vmax, convergence = configuration
    original = ieee13.context
    contexts, settings = [], []

    def configured_context():
        ctx = original()
        if vmax is not None:
            ctx.Text.Command("Edit Load.675b vmaxpu=" + str(vmax))
        if convergence is not None:
            ctx.Solution.Convergence(convergence)
        ctx.Loads.Name("675b")
        settings.append(
            {
                "model": ctx.Loads.Model(),
                "vminpu": ctx.Loads.Vminpu(),
                "vmaxpu": ctx.Loads.Vmaxpu(),
                "load_base_kv": ctx.Loads.kV(),
                "nominal_kw": ctx.Loads.kW(),
                "nominal_kvar": ctx.Loads.kvar(),
                "convergence_tolerance": ctx.Solution.Convergence(),
            }
        )
        contexts.append(ctx)
        return ctx

    # Both voltage and supplementary targets use the declared configuration.
    # The original post-hoc diagnostics assume native defaults and are omitted.
    with (
        patch.object(ieee13, "context", configured_context),
        patch.object(reference_checks, "context", configured_context),
        patch.object(reference_checks, "diagnose_reference", lambda protocol: {}),
    ):
        result = reference_checks.validate_extended_reference(protocol)
    if len(settings) != 2 or settings[0] != settings[1]:
        raise ValueError("Voltage and supplementary checks used different configurations")
    checks = [
        reference_checks.check(
            "voltage-" + row["node"],
            "published-phase-voltage",
            row["published_pu"],
            row["actual_pu"],
            result["published_voltage"]["tolerance_pu"],
            "pu",
        )
        for row in result["published_voltage"]["rows"]
    ] + result["additional_checks"]
    ctx = contexts[-1]
    ctx.Loads.Name("675b")
    return {
        "configuration": name,
        "declared_overrides": {"vmaxpu_675b": vmax, "convergence_tolerance": convergence},
        "effective_settings": settings[0],
        "converged": result["converged"],
        "passed": result["passed"],
        "passed_checks": sum(row["passed"] for row in checks),
        "total_checks": len(checks),
        "failed_checks": [row["id"] for row in checks if not row["passed"]],
        "checks": checks,
        "load_675b": {
            "voltage_on_load_base_pu": ctx.CktElement.VoltagesMagAng()[0] / (ctx.Loads.kV() * 1000),
            "actual_kw": sum(ctx.CktElement.Powers()[::2]),
            "actual_kvar": sum(ctx.CktElement.Powers()[1::2]),
        },
        "balance": result["balance_components"],
        "solver_version": result["solver_version"],
    }


def run_study():
    data = PROTOCOL.read_bytes()
    if hashlib.sha256(data).hexdigest() != PROTOCOL_SHA256:
        raise ValueError("Frozen reference targets changed")
    protocol = json.loads(data)
    before = input_hashes()
    with ProcessPoolExecutor(
        max_workers=1,
        max_tasks_per_child=1,
        mp_context=multiprocessing.get_context("spawn"),
    ) as pool:
        rows = [
            pool.submit(evaluate_configuration, config, protocol).result()
            for config in CONFIGURATIONS
        ]
    expected = (
        MODEL_FAILURES | {"power-balance-kW"},
        MODEL_FAILURES,
        set(),
        set(),
    )
    matched = all(
        row["converged"] and row["total_checks"] == 56 and set(row["failed_checks"]) == failures
        for row, failures in zip(rows, expected, strict=True)
    )
    if input_hashes() != before:
        raise ValueError("Reference-study inputs changed during execution")
    return {
        "kind": "reference-settings-sensitivity",
        "schema_version": 1,
        "verified_at": utc_now(),
        "design": "Post-hoc controls selected after inspecting the original mismatches; not blind confirmatory evidence",
        "inputs_sha256": before,
        "frozen_targets_and_tolerances": protocol,
        "rows": rows,
        "diagnostic_controls_matched": matched,
        "native_default_reference_passed": rows[0]["passed"],
        "scope": "Healthy reference circuit only. Changed VMaxpu applies to isolated diagnostic contexts. Original simulation inputs and frozen comparator remain unchanged. Derived currents and internal balances are not independent field observations.",
    }


def require_finite_json(report):
    # The relative comparator assumes finite values. Infinity can otherwise
    # satisfy inf <= tolerance * inf, falsely matching a finite measurement.
    try:
        json.dumps(report, allow_nan=False)
    except (ValueError, TypeError) as exc:
        raise ValueError("Sensitivity report contains non-finite or unsupported JSON data") from exc


def compare_reports(saved, actual):
    require_finite_json(saved)
    require_finite_json(actual)
    for key in (
        "kind",
        "schema_version",
        "inputs_sha256",
        "frozen_targets_and_tolerances",
        "rows",
        "diagnostic_controls_matched",
        "native_default_reference_passed",
    ):
        if _differences(saved[key], actual[key], key, 1e-7):
            raise ValueError("Saved sensitivity report differs from actual native execution")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    target = parser.add_mutually_exclusive_group()
    target.add_argument("--output", type=Path)
    target.add_argument("--verify-report", type=Path)
    args = parser.parse_args()
    if args.output and args.output.exists():
        parser.error("Output already exists; choose a new filename")
    saved = None
    if args.verify_report:
        try:
            saved = json.loads(args.verify_report.read_text(encoding="utf-8-sig"))
            require_finite_json(saved)
            if not isinstance(saved, dict):
                raise ValueError("Expected a sensitivity report JSON object")
        except (OSError, ValueError, TypeError) as exc:
            parser.error(str(exc))
    actual = run_study()
    if saved is not None:
        try:
            compare_reports(saved, actual)
        except (KeyError, TypeError, ValueError) as exc:
            parser.error(str(exc))
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(
            json.dumps(actual, indent=2, allow_nan=False) + "\n", encoding="utf-8"
        )
    print(
        json.dumps(
            {
                "diagnostic_controls_matched": actual["diagnostic_controls_matched"],
                "rows": [
                    {
                        key: row[key]
                        for key in (
                            "configuration",
                            "passed_checks",
                            "total_checks",
                            "failed_checks",
                        )
                    }
                    for row in actual["rows"]
                ],
            },
            indent=2,
        )
    )
    return 0 if actual["diagnostic_controls_matched"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
