import json
from pathlib import Path

import pytest


@pytest.fixture
def parse(monkeypatch):
    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[2] / "scripts"))
    from release_support import browser_counts

    return browser_counts


def report(path, statuses):
    mapping = {
        "passed": "expected",
        "failed": "unexpected",
        "skipped": "skipped",
        "interrupted": "unexpected",
        "flaky": "flaky",
    }
    stats = {k: 0 for k in ("expected", "unexpected", "skipped", "flaky")}
    tests = []
    for status in statuses:
        stats[mapping[status]] += 1
        tests.append(
            {
                "status": mapping[status],
                "expectedStatus": "passed",
                "results": (
                    [{"status": "failed"}, {"status": "passed"}]
                    if status == "flaky"
                    else [{"status": status}]
                ),
            }
        )
    value = {"suites": [{"suites": [{"specs": [{"tests": tests}]}]}], "stats": stats, "errors": []}
    path.write_text(json.dumps(value))
    return value


def test_structured_counts_do_not_need_the_console_summary(parse, tmp_path):
    path = tmp_path / "browser.json"
    report(path, ["passed"] * 15)
    assert parse(path) == {"passed": 15, "failed": 0, "skipped": 0, "errors": 0, "flaky": 0}


def test_structured_report_retains_failed_skipped_interrupted_and_flaky_outcomes(parse, tmp_path):
    path = tmp_path / "browser.json"
    report(path, ["passed", "failed", "skipped", "interrupted", "flaky"])
    assert parse(path) == {"passed": 1, "failed": 2, "skipped": 1, "errors": 1, "flaky": 1}


@pytest.mark.parametrize("damage", ["missing", "empty", "truncated", "inconsistent", "no-results"])
def test_missing_or_incomplete_browser_evidence_cannot_become_a_pass(parse, tmp_path, damage):
    path = tmp_path / "browser.json"
    value = report(path, [] if damage == "empty" else ["passed"])
    if damage == "missing":
        path.unlink()
    elif damage == "truncated":
        path.write_text('{"stats":')
    elif damage == "inconsistent":
        value["stats"]["expected"] = 99
        path.write_text(json.dumps(value))
    elif damage == "no-results":
        value["suites"][0]["suites"][0]["specs"][0]["tests"][0]["results"] = []
        path.write_text(json.dumps(value))
        assert parse(path)["errors"] == 1 and parse(path)["passed"] == 0
        return
    with pytest.raises((OSError, ValueError)):
        parse(path)
