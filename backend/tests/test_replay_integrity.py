"""Malformed replay evidence cannot pass numeric or Boolean comparison."""

import copy

import pytest

from gridsense.cases import RegressionInput
from gridsense.domain import Scenario
from gridsense.electrical import ElectricalEngine
from gridsense.episodes import EpisodeConfig, canonical_hash
from gridsense.regression import checksum, replay_regression, run_regression
from gridsense.service import _differences, evaluate, replay
from gridsense.session_store import CreateSession, SessionStore, replay_episode


@pytest.mark.parametrize(
    "left,right",
    [
        (float("inf"), 1.0),
        (1.0, float("inf")),
        (float("-inf"), 1.0),
        (1.0, float("-inf")),
        (float("nan"), 1.0),
        (1.0, float("nan")),
        (float("inf"), float("inf")),
        (float("nan"), float("nan")),
    ],
)
def test_comparison_rejects_nonfinite_values_on_either_side(left, right):
    assert _differences({"reading": [left]}, {"reading": [right]}, "record") == [
        "record.reading[0]"
    ]


@pytest.mark.parametrize("left,right", [(False, 0), (0, False), (True, 1), (1, True)])
def test_comparison_preserves_boolean_type(left, right):
    assert _differences({"feasible": left}, {"feasible": right}, "result") == ["result.feasible"]


def test_comparison_retains_finite_tolerance_and_exact_large_integer_identity():
    left = {"served_kw": 1000, "flags": [True, False], "count": 10**500}
    right = {"served_kw": 1000.00001, "flags": [True, False], "count": 10**500}
    assert not _differences(left, right)
    right["served_kw"] = 1000.1
    assert _differences(left, right) == [".served_kw"]
    assert _differences(10**500, 1.0, "reading") == ["reading"]


@pytest.fixture(scope="module")
def incident():
    return evaluate(Scenario(), "2026-01-01T12:00:00+00:00")


@pytest.mark.parametrize("value", [float("inf"), float("-inf"), float("nan")])
@pytest.mark.parametrize("location", ["before", "alternative"])
def test_native_incident_replay_rejects_nonfinite_recorded_power(incident, value, location):
    record = copy.deepcopy(incident)
    if location == "before":
        record["before"]["served_kw"] = value
    else:
        record["alternatives"][0]["result"]["served_kw"] = value
    result = replay(record)
    assert not result["matched"]
    assert any(path.endswith("served_kw") for path in result["differences"])


@pytest.mark.parametrize("location", ["before", "alternative"])
def test_native_incident_replay_rejects_numeric_feasibility_flags(incident, location):
    record = copy.deepcopy(incident)
    target = record["before"] if location == "before" else record["alternatives"][0]["result"]
    target["feasible"] = int(target["feasible"])
    result = replay(record)
    assert not result["matched"]
    assert any(path.endswith("feasible") for path in result["differences"])


def test_checksummed_regression_replay_rejects_numeric_boolean():
    record = run_regression(RegressionInput())
    assert replay_regression(record)["matched"]
    record["candidate"]["result"]["feasible"] = int(record["candidate"]["result"]["feasible"])
    record["content_sha256"] = checksum(record)
    result = replay_regression(record)
    assert not result["matched"]
    assert "candidate.result.feasible" in result["differences"]


def test_checksummed_episode_replay_rejects_numeric_boolean(tmp_path):
    store = SessionStore(tmp_path / "session.sqlite3", engine=ElectricalEngine())
    receipt = store.create(CreateSession(request_id="integrity", config=EpisodeConfig(horizon_s=2)))
    record = store.export(receipt["id"])
    assert replay_episode(record)["matched"]
    record["frames"][0]["electrical"]["feasible"] = int(
        record["frames"][0]["electrical"]["feasible"]
    )
    record["content_sha256"] = canonical_hash(
        {key: value for key, value in record.items() if key != "content_sha256"}
    )
    result = replay_episode(record)
    assert not result["matched"]
    assert "frames[0].electrical.feasible" in result["differences"]
