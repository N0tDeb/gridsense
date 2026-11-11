"""Supplemental reference checks, separate from restoration feasibility rules."""

import json
import math

from .ieee13 import ROOT, context, phase_voltages, validate_reference


def derived_current(row):
    """kVA / phase kV = A for a constant-PQ single-phase wye load."""
    return math.hypot(row["kw"], row["kvar"]) / (
        row["voltage_pu"] * row["base_ll_kv"] / math.sqrt(3)
    )


def check(identifier, category, expected, actual, tolerance, unit):
    error = abs(actual - expected)
    return {
        "id": identifier,
        "category": category,
        "expected": expected,
        "actual": actual,
        "absolute_error": error,
        "tolerance": tolerance,
        "unit": unit,
        "passed": math.isfinite(actual) and error <= tolerance,
    }


def balance_components(ctx):
    totals = []
    for names, kind in ((ctx.Loads.AllNames(), "Load"), (ctx.Capacitors.AllNames(), "Capacitor")):
        total = [0.0, 0.0]
        for name in names:
            ctx.Circuit.SetActiveElement(kind + "." + name)
            powers = ctx.CktElement.Powers()
            total[0] += sum(powers[::2])
            total[1] += sum(powers[1::2])
        totals.append(total)
    supply = [-x for x in ctx.Circuit.TotalPower()]
    losses = [x / 1000 for x in ctx.Circuit.Losses()]
    return {
        "source_injection_kw_kvar": supply,
        "loads_kw_kvar": totals[0],
        "capacitors_kw_kvar": totals[1],
        "losses_kw_kvar": losses,
        "residual_kw_kvar": [supply[i] - totals[0][i] - totals[1][i] - losses[i] for i in (0, 1)],
    }


def diagnose_reference(protocol):
    """Post-result diagnostics, not changes to the frozen primary experiment.

    Keep native-default failures visible. Independently instantiate each numerical
    control; never change context(), the bundled DSS model or restoration checks.
    """
    precise = context()
    precise.Solution.Convergence(1e-8)
    precise.Solution.Solve()
    precise.Loads.Name("675b")
    phase_volts = precise.CktElement.VoltagesMagAng()[0]
    vmax, kv = precise.Loads.Vmaxpu(), precise.Loads.kV()
    actual = precise.CktElement.Powers()[:2]
    source_load = next(r for r in protocol["loads"] if r["name"] == "675b")
    factor = (phase_volts / (kv * 1000 * vmax)) ** 2
    boundary_rows = [
        check(
            "675b-fallback-" + key,
            "model-consistency-not-independent-reference",
            source_load[key] * factor,
            actual[i],
            protocol["power_tolerance_kw_kvar"],
            key,
        )
        for i, key in enumerate(("kw", "kvar"))
    ]
    balance = balance_components(precise)
    controlled = context()
    controlled.Text.Command("Edit Load.675b vmaxpu=1.1")
    controlled.Solution.Convergence(1e-8)
    controlled.Solution.Solve()
    controlled.Loads.Name("675b")
    powers = controlled.CktElement.Powers()
    control_rows = [
        check(
            "675b-expanded-PQ-envelope-" + key,
            "post-hoc-model-control",
            source_load[key],
            powers[i],
            protocol["power_tolerance_kw_kvar"],
            key,
        )
        for i, key in enumerate(("kw", "kvar"))
    ]
    control_rows.append(
        check(
            "675b-expanded-PQ-envelope-current",
            "post-hoc-model-control",
            derived_current(source_load),
            controlled.CktElement.CurrentsMagAng()[0],
            max(
                protocol["current_absolute_floor_a"],
                derived_current(source_load) * protocol["current_relative_tolerance"],
            ),
            "A",
        )
    )
    return {
        "design": "Post-hoc diagnosis after primary frozen checks failed; not confirmatory holdout evidence",
        "documentation": "https://dss-extensions.org/dss-format/Load.html",
        "native_675b": {
            "load_base_kv": kv,
            "phase_volts": phase_volts,
            "vmaxpu": vmax,
            "actual_pu_on_load_base": phase_volts / (1000 * kv),
            "fallback_power_factor": factor,
        },
        "fallback_formula_checks": boundary_rows,
        "precision_control": {
            "convergence_tolerance": 1e-8,
            "converged": bool(precise.Solution.Converged()),
            "balance": balance,
            "balance_passed": all(
                abs(x) <= protocol["balance_tolerance_kw_kvar"] for x in balance["residual_kw_kvar"]
            ),
        },
        "constitutive_model_control": {
            "change": "Only this separate context: Load.675b vmaxpu=1.1; solver tolerance=1e-8",
            "converged": bool(controlled.Solution.Converged()),
            "checks": control_rows,
        },
        "conclusion": "Native Model=1 is constant PQ only inside its voltage envelope. Above VMaxpu=1.05 it reverts to impedance. The frozen constant-PQ expectation at 675b therefore does not describe native-default behavior. Tightening solver tolerance diagnoses the small balance residual; neither diagnostic overwrites primary results or validates restoration assumptions.",
    }


def configured_voltage_reference(ctx):
    """Read all published voltage targets from the same explicit solved context."""
    reference = json.loads(ROOT.joinpath("reference.json").read_text(encoding="utf-8"))
    actual = phase_voltages(ctx)
    rows = [
        {
            "node": node,
            "published_pu": expected,
            "actual_pu": actual[node],
            "error_pu": abs(actual[node] - expected),
            "passed": math.isfinite(actual[node])
            and abs(actual[node] - expected) <= reference["tolerance_pu"],
        }
        for node, expected in reference["voltages_pu"].items()
    ]
    return {
        "feeder": "IEEE 13-node electrical reference (no restoration ties)",
        "converged": bool(ctx.Solution.Converged()),
        "passed": bool(ctx.Solution.Converged()) and all(row["passed"] for row in rows),
        "max_error_pu": max(row["error_pu"] for row in rows),
        "rows": rows,
        "tolerance_pu": reference["tolerance_pu"],
        "reference": reference["source"],
        "solver_version": ctx.Basic.Version(),
        "scope": "Published voltage magnitudes under an explicitly configured reference context. Not validation of restoration ties, ampacities, protection or field operation.",
    }


def validate_extended_reference(protocol, *, configured_context=None):
    """Default behavior is preserved; an explicit context uses one solve for all targets."""
    native_defaults = configured_context is None
    voltage = validate_reference() if native_defaults else None
    ctx = context() if native_defaults else configured_context
    ctx.Solution.Solve()
    if not native_defaults:
        voltage = configured_voltage_reference(ctx)
    rows = []
    for load in protocol["loads"]:
        if ctx.Circuit.SetActiveElement("Load." + load["name"]) < 0:
            raise ValueError("Published reference load is absent from the circuit")
        expected = derived_current(load)
        tolerance = max(
            protocol["current_absolute_floor_a"], expected * protocol["current_relative_tolerance"]
        )
        rows.append(
            check(
                "load-current-" + load["name"],
                "derived-from-published-values",
                expected,
                ctx.CktElement.CurrentsMagAng()[0],
                tolerance,
                "A",
            )
        )
        powers = ctx.CktElement.Powers()
        for quantity, actual in (("kw", sum(powers[::2])), ("kvar", sum(powers[1::2]))):
            rows.append(
                check(
                    "load-" + quantity + "-" + load["name"],
                    "published-constant-power-allocation",
                    load[quantity],
                    actual,
                    protocol["power_tolerance_kw_kvar"],
                    quantity,
                )
            )
    ctx.Transformers.Name("xfm1")
    ncond = ctx.CktElement.NumConductors()
    # Second terminal, phase conductors only; explicitly exclude the neutral.
    actual_lv = ctx.CktElement.CurrentsMagAng()[::2][ncond : ncond + 3]
    expected_lv = [derived_current(r) for r in protocol["loads"] if r["name"].startswith("634")]
    for phase, (expected, actual) in enumerate(zip(expected_lv, actual_lv, strict=True), 1):
        rows.append(
            check(
                f"xfm1-lv-current-phase-{phase}",
                "derived-from-published-values",
                expected,
                actual,
                max(
                    protocol["current_absolute_floor_a"],
                    expected * protocol["current_relative_tolerance"],
                ),
                "A",
            )
        )
    rating = protocol["xfm1"]["kva"] / protocol["xfm1"]["lv_ll_kv"] / math.sqrt(3)
    rows.append(
        check(
            "xfm1-lv-loading",
            "derived-from-published-values",
            100 * max(expected_lv) / rating,
            100 * max(actual_lv) / rating,
            protocol["loading_tolerance_percentage_points"],
            "%",
        )
    )
    balance = balance_components(ctx)
    for index, unit in enumerate(("kW", "kvar")):
        residual = balance["residual_kw_kvar"][index]
        rows.append(
            check(
                "power-balance-" + unit,
                "internal-consistency-not-external-validation",
                0,
                residual,
                protocol["balance_tolerance_kw_kvar"],
                unit,
            )
        )
    return {
        "kind": "extended-electrical-reference",
        "converged": bool(ctx.Solution.Converged()),
        "passed": voltage["passed"]
        and bool(ctx.Solution.Converged())
        and all(r["passed"] for r in rows),
        "published_voltage": voltage,
        "additional_checks": rows,
        "balance_components": balance,
        "post_hoc_diagnostics": diagnose_reference(protocol) if native_defaults else None,
        "protocol": protocol,
        "solver_version": ctx.Basic.Version(),
        "scope": "Healthy electrical reference only. Current/loading expectations are derived from published voltage/PQ, not independent measured current tables. Power balance is internal consistency. Added restoration ties/ratings, physical devices and field protection are not validated.",
    }
