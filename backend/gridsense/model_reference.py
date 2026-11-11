"""A named native-model reference, without rewriting the frozen PQ comparison."""

import hashlib
import json
import math
from time import perf_counter

from .ieee13 import ROOT, context, phase_voltages
from .reference_checks import balance_components, check


def load_envelope(row, settings, voltage_tolerance):
    """Bounds from published voltage, never voltage read from the solved circuit.

    These reference inputs cover the constant-PQ and upper impedance branches
    of single-phase wye Model=1. Reject unsupported low-voltage cases rather than
    silently extrapolating a formula through another native model transition.
    """
    rated_kv = settings["rated_phase_kv"][row["name"]]
    phase_base = row["base_ll_kv"] / math.sqrt(3)
    lower = (row["voltage_pu"] - voltage_tolerance) * phase_base
    upper = (row["voltage_pu"] + voltage_tolerance) * phase_base
    if lower < rated_kv * settings["vminpu"] or lower <= 0:
        raise ValueError("Reference interval crosses the unsupported lower load-model branch")
    transition = rated_kv * settings["vmaxpu"]
    points = [lower, upper]
    if lower <= transition <= upper:
        points.append(transition)
    values = {"kw": [], "kvar": [], "current_a": []}
    for voltage_kv in points:
        factor = max(1.0, (voltage_kv / transition) ** 2)
        values["kw"].append(row["kw"] * factor)
        values["kvar"].append(row["kvar"] * factor)
        values["current_a"].append(math.hypot(row["kw"], row["kvar"]) * factor / voltage_kv)
    return {key: (min(v), max(v)) for key, v in values.items()}


def interval_check(identifier, bounds, actual, allowance, unit):
    return {
        "id": identifier,
        "category": "published-voltage-and-declared-model-envelope",
        "expected_lower": bounds[0],
        "expected_upper": bounds[1],
        "numeric_allowance": allowance,
        "actual": actual,
        "unit": unit,
        "passed": math.isfinite(actual)
        and bounds[0] - allowance <= actual <= bounds[1] + allowance,
    }


def convergence_study(settings):
    rows = []
    for multiplier in settings["load_multipliers"]:
        for tolerance in settings["convergence_tolerances"]:
            ctx = context()
            ctx.Solution.LoadMult(multiplier)
            ctx.Solution.Convergence(tolerance)
            start = perf_counter()
            ctx.Solution.Solve()
            elapsed = perf_counter() - start
            rows.append(
                {
                    "load_multiplier": multiplier,
                    "convergence_tolerance": tolerance,
                    "converged": bool(ctx.Solution.Converged()),
                    "iterations": ctx.Solution.Iterations(),
                    "solve_seconds": elapsed,
                    "balance_residual_kw_kvar": balance_components(ctx)["residual_kw_kvar"],
                }
            )
    return rows


def validate_model_reference(protocol, published_inputs):
    if (
        hashlib.sha256(ROOT.joinpath("model.dss").read_bytes()).hexdigest()
        != protocol["native_model_sha256"]
    ):
        raise ValueError(
            "Native reference model changed; review and identify the new configuration"
        )
    spec = protocol["load_model"]
    if (spec["model"], spec["phases"], spec["connection"]) != (1, 1, "wye"):
        raise ValueError("Reference envelope requires single-phase wye Model=1")
    ctx = context()
    ctx.Solution.Convergence(protocol["convergence_tolerance"])
    ctx.Solution.Solve()
    converged = bool(ctx.Solution.Converged())
    reference = json.loads(ROOT.joinpath("reference.json").read_text(encoding="utf-8"))
    actual_voltages = phase_voltages(ctx)
    voltage = [
        check(
            node,
            "independently-published-voltage",
            expected,
            actual_voltages[node],
            protocol["published_voltage_tolerance_pu"],
            "pu",
        )
        for node, expected in reference["voltages_pu"].items()
    ]
    model, envelopes, intervals = [], [], {}
    for row in published_inputs["loads"]:
        name = row["name"]
        ctx.Loads.Name(name)
        properties = {
            "model": (spec["model"], ctx.Loads.Model()),
            "phases": (spec["phases"], ctx.CktElement.NumPhases()),
            "delta": (0, int(ctx.Loads.IsDelta())),
            "rated_phase_kv": (spec["rated_phase_kv"][name], ctx.Loads.kV()),
            "vminpu": (spec["vminpu"], ctx.Loads.Vminpu()),
            "vmaxpu": (spec["vmaxpu"], ctx.Loads.Vmaxpu()),
        }
        for key, (expected, actual) in properties.items():
            model.append(
                check(name + "-" + key, "declared-model-contract", expected, actual, 1e-12, key)
            )
        interval = load_envelope(row, spec, protocol["published_voltage_tolerance_pu"])
        intervals[name] = interval
        powers = ctx.CktElement.Powers()
        measured = {
            "kw": sum(powers[::2]),
            "kvar": sum(powers[1::2]),
            "current_a": ctx.CktElement.CurrentsMagAng()[0],
        }
        for key, actual in measured.items():
            allowance = (
                protocol["current_numeric_allowance_a"]
                if key == "current_a"
                else protocol["power_numeric_allowance_kw_kvar"]
            )
            envelopes.append(
                interval_check(name + "-" + key, interval[key], actual, allowance, key)
            )
    ctx.Transformers.Name("xfm1")
    conductors = ctx.CktElement.NumConductors()
    currents = ctx.CktElement.CurrentsMagAng()[::2][conductors : conductors + 3]
    for phase, (name, current) in enumerate(
        zip(("634a", "634b", "634c"), currents, strict=True), 1
    ):
        envelopes.append(
            interval_check(
                f"xfm1-lv-current-{phase}",
                intervals[name]["current_a"],
                current,
                protocol["current_numeric_allowance_a"],
                "A",
            )
        )
    balance = balance_components(ctx)
    consistency = [
        check(
            "balance-" + unit,
            "internal-consistency",
            0,
            residual,
            protocol["balance_tolerance_kw_kvar"],
            unit,
        )
        for unit, residual in zip(("kW", "kvar"), balance["residual_kw_kvar"], strict=True)
    ]
    sensitivity = convergence_study(protocol["sensitivity"])
    selected = [
        r for r in sensitivity if r["convergence_tolerance"] == protocol["convergence_tolerance"]
    ]
    sensitivity_passed = bool(selected) and all(
        r["converged"]
        and all(
            abs(v) <= protocol["balance_tolerance_kw_kvar"] for v in r["balance_residual_kw_kvar"]
        )
        for r in selected
    )
    return {
        "configuration": protocol["configuration"],
        "converged": converged,
        "passed": converged
        and sensitivity_passed
        and all(r["passed"] for r in [*voltage, *model, *envelopes, *consistency]),
        "published_voltage_checks": voltage,
        "declared_model_checks": model,
        "model_envelope_checks": envelopes,
        "internal_balance_checks": consistency,
        "balance_components": balance,
        "convergence_study": sensitivity,
        "selected_convergence_passed": sensitivity_passed,
        "solver_version": ctx.Basic.Version(),
        "protocol": protocol,
        "scope": protocol["scope"],
        "original_pq_comparison": "Preserved separately; this configuration does not turn the original four mismatches into passed checks.",
    }
