"""Independently check packaged campaign tables, fingerprints and temporal replay."""

import hashlib
import json
from pathlib import Path

import pyarrow.parquet as pq
from gridsense.assurance import assurance_hash, assess_temporal_trace, replay_defect
from gridsense.regression import harness_hash
from gridsense.service import _differences, implementation_hash
from gridsense.failure_search import search_hash
from gridsense.temporal import DeviceEvent, TemporalInput, simulate_events

ROOT = Path(__file__).resolve().parents[1]


def check(condition, message):
    if not condition:
        raise ValueError(message)


def main():
    def study(folder, filename="results.json"):
        return json.loads((ROOT / "experiments" / folder / filename).read_text(encoding="utf-8"))

    def script_digest(name):
        return hashlib.sha256((ROOT / "experiments" / name).read_bytes()).hexdigest()

    model_reference = study("model_reference_results")
    model_protocol = (ROOT / "experiments/protocols/model_reference.json").read_bytes()
    check(
        model_reference["protocol_sha256"] == hashlib.sha256(model_protocol).hexdigest()
        and model_reference["protocol"] == json.loads(model_protocol),
        "Model-aware reference protocol mismatch",
    )
    check(
        model_reference["checker_sha256"]
        == hashlib.sha256((ROOT / "backend/gridsense/model_reference.py").read_bytes()).hexdigest()
        and model_reference["runner_sha256"] == script_digest("run_model_reference.py"),
        "Model-aware reference source mismatch",
    )
    check(
        model_reference["passed"]
        and model_reference["selected_convergence_passed"]
        and all(
            r["passed"]
            for key in (
                "published_voltage_checks",
                "declared_model_checks",
                "model_envelope_checks",
                "internal_balance_checks",
            )
            for r in model_reference[key]
        ),
        "Model-aware reference check failed",
    )
    grid = study("results", "benchmark.json")
    check(
        grid["manifest"]["implementation_sha256"] == implementation_hash(), "Grid source mismatch"
    )
    check(grid["cases"] == 72 and len(grid["rows"]) == 216, "Grid denominator mismatch")
    check(
        pq.read_table(ROOT / "experiments/results/benchmark.parquet").to_pylist() == grid["rows"],
        "Grid JSON / Parquet mismatch",
    )
    search = study("search_results")
    sm = search["manifest"]
    check(
        sm["core_implementation_sha256"] == implementation_hash()
        and sm["search_implementation_sha256"] == search_hash(),
        "Search source mismatch",
    )
    check(
        sm["benchmark_script_sha256"] == script_digest("run_search_benchmark.py"),
        "Search runner mismatch",
    )
    check(
        len(search["runs"]) == 48 and sum(r["evaluations"] for r in search["runs"]) == 1152,
        "Search denominator mismatch",
    )
    transfer = study("verification_results")
    tm = transfer["manifest"]
    check(
        tm["harness_sha256"] == harness_hash()
        and tm["benchmark_sha256"] == script_digest("run_verification_benchmark.py"),
        "Transfer source mismatch",
    )
    check(
        tm["search_artifact_sha256"]
        == hashlib.sha256(
            (ROOT / "experiments/search_results/results.json").read_bytes()
        ).hexdigest(),
        "Transfer search input mismatch",
    )
    check(
        len(transfer["cases"]) == 192 and len(transfer["rows"]) == 576,
        "Transfer denominator mismatch",
    )
    quality = study("quality_results")
    qm = quality["manifest"]
    protocol_bytes = (ROOT / "experiments/protocols/quality.json").read_bytes()
    check(
        qm["protocol_sha256"] == hashlib.sha256(protocol_bytes).hexdigest()
        and qm["protocol"] == json.loads(protocol_bytes),
        "Quality protocol mismatch",
    )
    qp = qm["protocol"]
    check(
        (qp["core_sha256"], qp["search_sha256"], qp["harness_sha256"])
        == (implementation_hash(), search_hash(), harness_hash()),
        "Quality source mismatch",
    )
    check(
        qm["runner_sha256"] == script_digest("run_quality_benchmark.py"), "Quality runner mismatch"
    )
    check(
        len(quality["search_runs"]) == 64
        and len(quality["cases"]) == 192
        and len(quality["controller_rows"]) == 576,
        "Quality denominator mismatch",
    )

    directory = ROOT / "experiments/assurance_results"
    result = json.loads((directory / "results.json").read_text(encoding="utf-8"))
    inputs = json.loads((directory / "frozen_inputs.json").read_text(encoding="utf-8"))
    manifest, rows = result["manifest"], result["rows"]
    check(inputs["manifest"] == manifest, "Expanded input and result manifests differ")
    check(
        manifest["protocol_sha256"]
        == hashlib.sha256((ROOT / "experiments/protocols/assurance.json").read_bytes()).hexdigest(),
        "Protocol digest changed",
    )
    check(
        manifest["runner_sha256"]
        == hashlib.sha256(
            (ROOT / "experiments/run_assurance_benchmark.py").read_bytes()
        ).hexdigest(),
        "Runner digest changed",
    )
    check(
        manifest["assurance_sha256"] == assurance_hash()
        and manifest["harness_sha256"] == harness_hash(),
        "Implementation digest changed",
    )
    check(len(rows) == 224 and len(inputs["cases"]) == 32, "Case count changed")
    for item in inputs["cases"]:
        group = [r for r in rows if r["id"] == item["id"]]
        check(
            len(group) == 7 and all(r["case"] == item["case"] for r in group),
            "Expanded case differs from evaluated input",
        )
    flat = pq.read_table(directory / "outcomes.parquet").to_pylist()
    expected = [
        {
            key: r[key]
            for key in (
                "id",
                "partition",
                "family",
                "variant",
                "detected",
                "category",
                "execution_adapter_solves",
            )
        }
        | {"reference_passed": r["reference"]["passed"]}
        for r in rows
    ]
    check(flat == expected, "JSON / Parquet mismatch")
    for summary in result["summary"]["variants"]:
        group = [
            r
            for r in rows
            if r["partition"] == summary["partition"] and r["variant"] == summary["variant"]
        ]
        check(summary["cases"] == len(group), "Summary denominator mismatch")
        check(
            summary["detections"] == sum(r["detected"] for r in group), "Summary detection mismatch"
        )
        check(
            summary["reference_passed"] == sum(r["reference"]["passed"] for r in group),
            "Reference denominator mismatch",
        )
        check(
            summary["first_detection_case"]
            == next((i + 1 for i, r in enumerate(group) if r["detected"]), None),
            "First detection mismatch",
        )
    for summary in result["summary"]["families"]:
        group = [
            r
            for r in rows
            if r["family"] == summary["family"] and r["variant"] == summary["controller"]
        ]
        eligible = [
            r
            for r in group
            if r["attainability"]["initial_electrical_pass"]
            and r["attainability"]["truth_attainable"]
        ]
        check(
            summary["cases"] == len(group) and summary["eligible_cases"] == len(eligible),
            "Family denominator mismatch",
        )
        check(
            summary["full_contract_passes"] == sum(r["candidate"]["passed"] for r in group),
            "Family contract mismatch",
        )
        check(
            summary["electrical_passes"] == sum(r["candidate"]["electrical_pass"] for r in group),
            "Family electrical mismatch",
        )
        check(
            summary["eligible_full_contract_passes"]
            == sum(r["candidate"]["passed"] for r in eligible),
            "Eligible result mismatch",
        )
    for row in rows:
        check(
            not row["detected"] or row["reference"]["passed"],
            "Detection without a passing reference",
        )
        if row["variant"].endswith("control"):
            check(not row["detected"], "Negative control false detection")
    temporal_replays = []
    for row in result["temporal_rows"]:
        request = TemporalInput.model_validate(row["request"])
        events = [DeviceEvent.model_validate(e) for e in row["simulation"]["events"]]
        actual = simulate_events(request, events)
        check(
            not _differences(row["simulation"], actual, "temporal", 1e-7),
            "Physical temporal replay mismatch",
        )
        for variant, previous in row["outcomes"].items():
            check(
                not _differences(previous, assess_temporal_trace(actual, variant), variant, 1e-7),
                "Temporal tracker replay mismatch",
            )
        temporal_replays.append(
            {
                "timeout_s": row["timeout_s"],
                "delay_s": row["delay_s"],
                "failed_close": row["failed_close"],
                "matched": True,
            }
        )
    for summary in result["summary"]["temporal"]:
        check(
            summary["detections"]
            == sum(r["outcomes"][summary["variant"]]["detected"] for r in result["temporal_rows"]),
            "Temporal count mismatch",
        )
    reproductions = []
    for item in result["reproducers"]:
        record = json.loads((directory / item["file"]).read_text(encoding="utf-8"))
        replay = replay_defect(record)
        check(replay["matched"], "Defect replay mismatch")
        reproductions.append({"variant": item["variant"], **replay})
    unique_costs = {r["id"]: r["preparation_cost"] for r in rows}
    check(
        result["costs"]["snapshot_preparation_solves"]
        == sum(sum(c.values()) for c in unique_costs.values()),
        "Shared cost was duplicated or omitted",
    )
    check(
        result["costs"]["snapshot_execution_solves"]
        == sum(r["execution_adapter_solves"] for r in rows),
        "Paired execution cost mismatch",
    )
    print(
        json.dumps(
            {
                "all_study_fingerprints_match": True,
                "all_study_denominators_match": True,
                "json_parquet_match": True,
                "summary_counts_match": True,
                "fingerprints_match": True,
                "snapshot_pairs": len(rows),
                "temporal_replays": temporal_replays,
                "defect_replays": reproductions,
                "campaign_costs": result["costs"],
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
