import pytest
from gridsense.domain import Scenario, SweepInput
from gridsense.network import initial_state, load_network
from gridsense.planning import choose_action
from gridsense.service import evaluate, observations, replay, sweep

AT = "2026-01-01T12:00:00+00:00"


def test_default_incident_exposes_stale_telemetry_failure():
    incident = evaluate(Scenario(), AT)
    assert incident["decisions"]["nominal"]["selected_action"]["id"] == "tie_b"
    assert not incident["outcomes"]["nominal"]["result"]["feasible"]
    assert incident["decisions"]["guarded"]["selected_action"]["id"] == "tie_c"
    assert incident["outcomes"]["guarded"]["result"]["feasible"]


def test_controller_decision_does_not_read_hidden_actual_load():
    obs = observations(Scenario(), AT, load_network())
    low = choose_action(obs, initial_state({"a": 1, "b": 0.5, "c": 0.9}), "guarded")
    high = choose_action(obs, initial_state({"a": 1, "b": 2, "c": 0.9}), "guarded")
    assert low.model_dump() == high.model_dump()


def test_different_donors_can_win_for_different_observations():
    low = evaluate(
        Scenario(load_b=0.7, reported_b=0.7, load_c=1.1, telemetry_age_s=0, uncertainty_pct=0), AT
    )
    high = evaluate(
        Scenario(load_b=1.5, reported_b=1.5, load_c=0.9, telemetry_age_s=0, uncertainty_pct=0), AT
    )
    assert low["decisions"]["nominal"]["selected_action"]["id"] == "tie_b"
    assert high["decisions"]["nominal"]["selected_action"]["id"] == "tie_c"


def test_full_routes_rejected_when_only_critical_restoration_is_feasible():
    incident = evaluate(
        Scenario(load_b=1.65, reported_b=1.65, load_c=1.6, telemetry_age_s=0, uncertainty_pct=0), AT
    )
    out = incident["outcomes"]["guarded"]
    assert "partial" in out["action"]["id"]
    assert out["result"]["feasible"]
    assert out["result"]["critical_served_kw"] == pytest.approx(400, abs=0.1)


def test_replay_reconstructs_every_recorded_branch():
    incident = evaluate(Scenario(), AT)
    result = replay(incident)
    assert result["matched"]
    assert len(result["alternatives"]) == len(incident["alternatives"]) == 5
    incident["alternatives"][1]["result"]["served_kw"] += 10
    assert not replay(incident)["matched"]


def test_replay_rejects_incompatible_code_and_tampered_network():
    incident = evaluate(Scenario(), AT)
    incident["manifest"]["implementation_sha256"] = "outdated"
    with pytest.raises(ValueError, match="implementation"):
        replay(incident)
    incident = evaluate(Scenario(), AT)
    incident["manifest"]["network"]["lines"][0]["normal_amps"] += 1
    with pytest.raises(ValueError, match="integrity"):
        replay(incident)


def test_measurement_rows_retain_time_value_and_quality():
    obs = observations(Scenario(), AT, load_network())
    west = next(row for row in obs.rows if row["load_id"] == "b1")
    east = next(row for row in obs.rows if row["load_id"] == "c1")
    assert west["value"] == 450 * 0.85
    assert west["measurement_at"] == "2026-01-01T11:58:00+00:00"
    assert west["quality"] == "stale" and east["quality"] == "current"


def test_sweep_holds_controller_information_fixed_and_reveals_violation():
    result = sweep(SweepInput(points=4))
    nominal = [r for r in result["rows"] if r["policy"] == "nominal"]
    assert len({r["action"] for r in nominal}) == 1
    assert nominal[0]["feasible"] and not nominal[-1]["feasible"]
    assert len(result["rows"]) == 12


def test_guarded_policy_can_be_conservative_without_claiming_guarantees():
    scenario = Scenario(load_b=0.7, reported_b=1.5, load_c=1.4, uncertainty_pct=80)
    incident = evaluate(scenario, AT)
    assert (
        incident["outcomes"]["guarded"]["result"]["restored_kw"]
        < incident["outcomes"]["oracle"]["result"]["restored_kw"]
    )
    assert "not a guarantee" in incident["decisions"]["guarded"]["rationale"]
