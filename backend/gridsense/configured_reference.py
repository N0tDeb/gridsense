"""Versioned constant-PQ reference configuration, separate from native restoration."""

import hashlib
import json

from .ieee13 import ROOT, context
from .reference_checks import check, validate_extended_reference
from .service import _differences

CONFIGURATION = "ieee13-constant-pq-reference-v1"
MODEL_SHA256 = "e78ad86910eb7e03de4cc09dbffdb508061a2030617e4e928ba16674e983adae"
VOLTAGE_SHA256 = "44bd63ba5edbf8ab7a2f6d9b77008ec36017940f676a06c0472bbb24aed544f9"
PROTOCOL_SHA256 = "7648402dcbfc3b61ff183d2448922ec437bc9c08c02e838ee4796b3334267774"
LOAD_SETTINGS = {
    "name": "675b",
    "model": 1,
    "vminpu": 0.95,
    "vmaxpu": 1.1,
    "rated_phase_kv": 2.4,
    "nominal_kw": 68.0,
    "nominal_kvar": 60.0,
}


def reference_rows(result):
    return [
        check(
            "voltage-" + row["node"],
            "published-phase-voltage",
            row["published_pu"],
            row["actual_pu"],
            result["published_voltage"]["tolerance_pu"],
            "pu",
        )
        for row in result["published_voltage"]["rows"]
    ] + result["additional_checks"]


def validate_configured_reference(profile, protocol):
    # v1 fixes the declared configuration. Other models/settings need another
    # named version, rather than silently retuning a saved passing profile.
    expected = {
        "schema_version": 1,
        "configuration": CONFIGURATION,
        "native_model_sha256": MODEL_SHA256,
        "published_voltage_file_sha256": VOLTAGE_SHA256,
        "published_protocol_sha256": PROTOCOL_SHA256,
        "convergence_tolerance": 1e-8,
        "load_override": LOAD_SETTINGS,
    }
    if _differences({key: profile.get(key) for key in expected}, expected, "profile", 0):
        raise ValueError("Reference profile differs from the declared v1 configuration")
    try:
        json.dumps(profile, allow_nan=False)
        json.dumps(protocol, allow_nan=False)
    except (ValueError, TypeError) as exc:
        raise ValueError("Reference inputs must contain finite JSON values") from exc
    for name, expected_hash in (("model.dss", MODEL_SHA256), ("reference.json", VOLTAGE_SHA256)):
        if hashlib.sha256(ROOT.joinpath(name).read_bytes()).hexdigest() != expected_hash:
            raise ValueError("Bundled reference model or published voltages changed")
    ctx = context()
    ctx.Loads.Name("675b")
    # Check the native model before applying the single declared load override.
    actual = {
        "name": ctx.Loads.Name(),
        "model": ctx.Loads.Model(),
        "vminpu": ctx.Loads.Vminpu(),
        "vmaxpu": ctx.Loads.Vmaxpu(),
        "rated_phase_kv": ctx.Loads.kV(),
        "nominal_kw": ctx.Loads.kW(),
        "nominal_kvar": ctx.Loads.kvar(),
    }
    if actual != {**LOAD_SETTINGS, "vmaxpu": 1.05}:
        raise ValueError("Native 675b model differs from the declared profile predecessor")
    ctx.Loads.Vmaxpu(LOAD_SETTINGS["vmaxpu"])
    ctx.Solution.Convergence(profile["convergence_tolerance"])
    result = validate_extended_reference(protocol, configured_context=ctx)
    rows = reference_rows(result)
    ctx.Loads.Name("675b")
    settings_match = (
        ctx.Loads.Vmaxpu() == LOAD_SETTINGS["vmaxpu"]
        and ctx.Solution.Convergence() == profile["convergence_tolerance"]
    )
    result.update(
        {
            "kind": "configured-electrical-reference",
            "schema_version": 1,
            "configuration": CONFIGURATION,
            "profile": profile,
            "design": profile["design"],
            "scope": profile["scope"],
            "effective_settings": {
                **actual,
                "vmaxpu": ctx.Loads.Vmaxpu(),
                "convergence_tolerance": ctx.Solution.Convergence(),
            },
            "load_voltage_on_rated_base_pu": ctx.CktElement.VoltagesMagAng()[0]
            / (1000 * ctx.Loads.kV()),
            "checks": rows,
            "passed_checks": sum(row["passed"] for row in rows),
            "total_checks": len(rows),
            "failed_checks": [row["id"] for row in rows if not row["passed"]],
            "passed": result["passed"] and settings_match and len(rows) == 56,
        }
    )
    return result
