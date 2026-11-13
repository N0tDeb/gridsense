import copy
import json
from pathlib import Path

import pytest

from gridsense.model_reference import load_envelope, validate_model_reference

PROTOCOLS = Path(__file__).resolve().parents[2] / "experiments/protocols"


def inputs():
    return (
        json.loads((PROTOCOLS / "model_reference.json").read_text()),
        json.loads((PROTOCOLS / "electrical.json").read_text()),
    )


def test_native_reference_keeps_independent_and_conditional_evidence_separate():
    protocol, published = inputs()
    result = validate_model_reference(protocol, published)
    assert result["passed"]
    assert len(result["published_voltage_checks"]) == 29
    assert len(result["model_envelope_checks"]) == 24
    assert {r["category"] for r in result["internal_balance_checks"]} == {"internal-consistency"}
    assert {r["category"] for r in result["model_envelope_checks"]} == {
        "published-voltage-and-declared-model-envelope"
    }
    assert len(result["convergence_study"]) == 12
    assert result["selected_convergence_passed"]
    vmax = next(r for r in result["declared_model_checks"] if r["id"] == "675b-vmaxpu")
    assert vmax["actual"] == 1.05  # Passing did not require a different native load law.


def test_changed_published_power_fails_instead_of_becoming_a_solver_derived_target():
    protocol, published = inputs()
    published = copy.deepcopy(published)
    next(r for r in published["loads"] if r["name"] == "675b")["kw"] *= 2
    result = validate_model_reference(protocol, published)
    assert not result["passed"]
    assert not next(r for r in result["model_envelope_checks"] if r["id"] == "675b-kw")["passed"]
    assert all(r["passed"] for r in result["internal_balance_checks"])


def test_current_envelope_includes_its_interior_transition_minimum():
    row = {"name": "one", "kw": 3, "kvar": 4, "voltage_pu": 1.05, "base_ll_kv": 3**0.5}
    settings = {"rated_phase_kv": {"one": 1}, "vminpu": 0.95, "vmaxpu": 1.05}
    envelope = load_envelope(row, settings, 0.05)
    assert envelope["current_a"][0] == pytest.approx(5 / 1.05)
    assert envelope["current_a"][1] == pytest.approx(5)
    assert envelope["kw"][0] == pytest.approx(3)
    with pytest.raises(ValueError, match="lower"):
        load_envelope(row, settings, 0.2)


def test_changed_model_identity_is_rejected_before_numerical_comparison():
    protocol, published = inputs()
    protocol["native_model_sha256"] = "different-model"
    with pytest.raises(ValueError, match="Native reference model changed"):
        validate_model_reference(protocol, published)
