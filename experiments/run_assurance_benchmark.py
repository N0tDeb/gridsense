"""Frozen, finite fault-injection study. Run from the installed project root.

Outputs refuse replacement: use --output-dir var/my-assurance-rerun for a new run.
The campaign is deterministic; timings are descriptive, not portable guarantees.
"""

import argparse
import hashlib
import itertools
import json
import platform
from pathlib import Path
from time import perf_counter
from unittest.mock import patch

import pyarrow as pa
import pyarrow.parquet as pq
from gridsense import __version__
from gridsense.assurance import (
    VARIANTS,
    MeteredPlant,
    assurance_hash,
    assess_temporal_trace,
    compare_episode,
    prepare_episode,
    reduce_episode,
    replay_defect,
)
from gridsense.cases import PortableCase
from gridsense.plants import plant_for
from gridsense.regression import harness_hash
from gridsense.service import utc_now
from gridsense.temporal import DeviceEvent, TemporalInput, simulate_events

ROOT = Path(__file__).resolve().parent
PROTOCOL = ROOT / "protocols/assurance.json"
PROTOCOL_SHA256 = "471de53ffabc44635db58e4a6126110e3c500c0a10db2ce8757ddff930679a42"


def write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    temporary.replace(path)


def load_protocol():
    data = PROTOCOL.read_bytes()
    if hashlib.sha256(data).hexdigest() != PROTOCOL_SHA256:
        raise ValueError("Frozen protocol changed; use a separately versioned experiment")
    protocol = json.loads(data)
    if protocol["harness_sha256"] != harness_hash():
        raise ValueError("Trusted harness differs from the frozen protocol")
    if list(protocol["variants"]) != list(VARIANTS):
        raise ValueError("Experimental controller registry differs from frozen protocol")
    return protocol


def decode_cases(protocol):
    result = []
    for row in protocol["cases"]:
        item = dict(zip(protocol["columns"], row, strict=True))
        case = PortableCase.model_validate(
            {
                "title": item["id"] + " / " + item["family"],
                "feeder": item["feeder"],
                "fault": item["fault"],
                "scenario": {
                    "load_a": item["load_a"],
                    "load_b": item["load_b"],
                    "load_c": item["load_c"],
                    "reported_b": item["reported_b"],
                    "telemetry_age_s": item["age_s"],
                    "uncertainty_pct": item["uncertainty_pct"],
                },
                "contract": {
                    "minimum_restored_kw": item["minimum_restored_kw"],
                    "minimum_critical_kw": item["minimum_critical_kw"],
                },
                "origin": "Frozen author-designed assurance matrix " + PROTOCOL_SHA256,
            }
        )
        result.append(({k: item[k] for k in ("id", "partition", "family")}, case))
    if len({meta["id"] for meta, _ in result}) != len(result):
        raise ValueError("Duplicate case identity")
    return result


def summarize(rows, temporal_rows):
    variants, families = [], []
    for partition, variant in itertools.product(("development", "reserved"), VARIANTS):
        selected = [r for r in rows if r["partition"] == partition and r["variant"] == variant]
        first = next((i + 1 for i, r in enumerate(selected) if r["detected"]), None)
        variants.append(
            {
                "partition": partition,
                "variant": variant,
                "cases": len(selected),
                "reference_passed": sum(r["reference"]["passed"] for r in selected),
                "detections": sum(r["detected"] for r in selected),
                "first_detection_case": first,
                "cumulative_shared_and_pair_solves_to_first": sum(
                    sum(r["preparation_cost"].values()) + r["execution_adapter_solves"]
                    for r in selected[:first]
                )
                if first
                else None,
                "changed_actions_or_rejections": sum(
                    r["candidate"].get("rejected", False)
                    or r["candidate"]["action"] != r["reference"]["action"]
                    for r in selected
                ),
            }
        )
    for family in dict.fromkeys(r["family"] for r in rows if r["partition"] == "reserved"):
        for variant in ("nominal-control", "guarded-control"):
            group = [r for r in rows if r["family"] == family and r["variant"] == variant]
            eligible = [
                r
                for r in group
                if r["attainability"]["initial_electrical_pass"]
                and r["attainability"]["truth_attainable"]
            ]
            families.append(
                {
                    "family": family,
                    "controller": variant,
                    "cases": len(group),
                    "electrical_passes": sum(r["candidate"]["electrical_pass"] for r in group),
                    "full_contract_passes": sum(r["candidate"]["passed"] for r in group),
                    "eligible_cases": len(eligible),
                    "eligible_full_contract_passes": sum(
                        r["candidate"]["passed"] for r in eligible
                    ),
                }
            )
    temporal = [
        {
            "variant": variant,
            "cases": len(temporal_rows),
            "detections": sum(r["outcomes"][variant]["detected"] for r in temporal_rows),
        }
        for variant in (
            "confirmed-control",
            "optimistic-command",
            "timeout-success",
            "inverted-position",
        )
    ]
    return {"variants": variants, "families": families, "temporal": temporal}


def markdown(summary, costs, reproducers):
    lines = [
        "# Controller assurance study",
        "",
        "Fixed, previously inspected cases on known models. Development/reserved groups "
        "are not an unseen external holdout; the study measures bounded testing utility.",
        "",
        "## Reserved controller variants",
        "",
        "| Variant | Cases | Reference passes | Attributable detections | First case |",
        "|---|---:|---:|---:|---:|",
    ]
    for r in summary["variants"]:
        if r["partition"] == "reserved":
            lines.append(
                f"| {r['variant']} | {r['cases']} | {r['reference_passed']} | {r['detections']} | {r['first_detection_case'] or 'No hit'} |"
            )
    lines += [
        "",
        "A missed or unexercised mutation is not proof of equivalence. The ranking-sign "
        "mutation is an intentionally obvious control. Ignoring uncertainty is an ablation of the "
        "guarded specification, not evidence that nominal control is universally defective. "
        "Action-interface rejections are not counted as electrical discoveries.",
        "",
        "## Reserved family results",
        "",
        "| Family | Controller | Electrical / all | Full contract / all | Full contract / eligible |",
        "|---|---|---:|---:|---:|",
    ]
    for r in summary["families"]:
        lines.append(
            f"| {r['family']} | {r['controller']} | {r['electrical_passes']}/{r['cases']} | {r['full_contract_passes']}/{r['cases']} | {r['eligible_full_contract_passes']}/{r['eligible_cases']} |"
        )
    lines += [
        "",
        "Eligible means initially electrically feasible AND truth-attainable within the "
        "bounded action set. Privileged attainability is used for analysis only, never selection. "
        "These fixed cases have no sampling distribution warranting field confidence intervals.",
        "",
        "## One-command status faults",
        "",
        "| Variant | Cases | Violating episodes |",
        "|---|---:|---:|",
    ]
    for r in summary["temporal"]:
        lines.append(f"| {r['variant']} | {r['cases']} | {r['detections']} |")
    lines += [
        "",
        "Physical actuator traces are generated by the unchanged OpenDSS-backed temporal "
        "engine. Trackers receive messages only. This is a narrow status-interpretation study, "
        "not multi-device control or protection validation.",
        "",
        "## Reproduction and costs",
        "",
        f"- Retained original/reduced snapshot pairs: {len(reproducers)}; all strict replay results are in results.json.",
        f"- Shared snapshot preparation: {costs['snapshot_preparation_solves']} adapter solves.",
        f"- Snapshot paired execution: {costs['snapshot_execution_solves']} adapter solves.",
        f"- Temporal physical traces: {costs['temporal_solves']} adapter solves.",
        f"- Additional original rechecks: {costs['original_recheck_solves']}; reduction: {costs['reduction_solves']}; replay: {costs['replay_solves']} adapter solves.",
        "- Costs count completed domain-adapter solves, including intermediate switch states, not DSS iterations or context initialization.",
        "- Per-variant cumulative discovery costs include the shared preparation plus that pair only; do not sum them to obtain campaign cost.",
        "- Reduction preserves the first failure category and fixed service contract; no global-minimality claim.",
        "- All input cases, predictions, actual outcomes, failures, no-hits and reduction trials remain in JSON; flat outcomes are mirrored in Parquet.",
        "",
    ]
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, default=ROOT / "assurance_results")
    args = parser.parse_args()
    protocol = load_protocol()
    cases = decode_cases(protocol)
    if args.output_dir.exists() and any(args.output_dir.iterdir()):
        parser.error("Output directory is not empty; choose a new location to preserve evidence")
    args.output_dir.mkdir(parents=True, exist_ok=True)
    started = perf_counter()
    manifest = {
        "version": __version__,
        "started_at": utc_now(),
        "protocol": protocol,
        "protocol_sha256": PROTOCOL_SHA256,
        "assurance_sha256": assurance_hash(),
        "harness_sha256": harness_hash(),
        "runner_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "python": platform.python_version(),
        "platform": platform.platform(),
    }
    # Persist expanded inputs before any solve, including reserved inputs and priming rule.
    write_json(
        args.output_dir / "frozen_inputs.json",
        {
            "manifest": manifest,
            "cases": [{**meta, "case": case.model_dump(mode="json")} for meta, case in cases],
        },
    )
    rows, temporal_rows, first = [], [], {}
    costs = dict.fromkeys(
        (
            "snapshot_preparation_solves",
            "snapshot_execution_solves",
            "temporal_solves",
            "original_recheck_solves",
            "reduction_solves",
            "replay_solves",
        ),
        0,
    )
    for meta, case in cases:
        before = perf_counter()
        prepared = prepare_episode(case, assess_attainability=True)
        costs["snapshot_preparation_solves"] += sum(prepared["costs"].values())
        for variant in VARIANTS:
            pair = compare_episode(case, variant, prepared=prepared)
            costs["snapshot_execution_solves"] += pair["execution_adapter_solves"]
            row = {
                **meta,
                "feeder": case.feeder,
                "fault": case.fault,
                "case": case.model_dump(mode="json"),
                **pair,
                "preparation_cost": prepared["costs"],
                "attainability": prepared["attainability"],
            }
            rows.append(row)
            if meta["partition"] == "reserved" and pair["detected"]:
                first.setdefault(variant, case)
        print(f"{meta['partition']} {meta['id']}: {perf_counter() - before:.2f}s", flush=True)
    snapshot_seconds = perf_counter() - started
    temporal_started = perf_counter()
    settings = protocol["temporal"]
    for timeout, delay, failed in itertools.product(
        settings["timeouts_s"], settings["confirmation_delays_s"], settings["failed_close"]
    ):
        request = TemporalInput(timeout_s=timeout)
        events = [DeviceEvent(kind="delay_confirmation", delay_s=delay)]
        if failed:
            events.append(DeviceEvent(kind="fail_close"))
        meters = []

        def measured_factory(case):
            meter = MeteredPlant(plant_for(case))
            meters.append(meter)
            return meter

        with patch("gridsense.temporal.plant_for", measured_factory):
            simulation = simulate_events(request, events)
        cost = sum(m.adapter_solves for m in meters)
        costs["temporal_solves"] += cost
        temporal_rows.append(
            {
                "timeout_s": timeout,
                "delay_s": delay,
                "failed_close": failed,
                "request": request.model_dump(mode="json"),
                "simulation": simulation,
                "adapter_solves": cost,
                "outcomes": {v: assess_temporal_trace(simulation, v) for v in settings["variants"]},
            }
        )
    temporal_seconds = perf_counter() - temporal_started
    reproducers = []
    for variant, case in first.items():
        before = perf_counter()
        record = reduce_episode(case, variant, protocol["reduction_budget_per_detected_variant"])
        reduction_seconds = perf_counter() - before
        file = args.output_dir / "reproducers" / (variant + ".json")
        write_json(file, record)
        before = perf_counter()
        replay = replay_defect(record)
        costs["original_recheck_solves"] += record["cost"]["original_recheck_adapter_solves"]
        costs["reduction_solves"] += record["cost"]["reduction_adapter_solves"]
        costs["replay_solves"] += replay["adapter_solves"]
        reproducers.append(
            {
                "variant": variant,
                "file": file.relative_to(args.output_dir).as_posix(),
                "category": record["original"]["category"],
                "trials": len(record["trials"]),
                "complexity_before": record["complexity_before"],
                "complexity_after": record["complexity_after"],
                "cost": record["cost"],
                "replay": replay,
                "reduction_seconds": reduction_seconds,
                "replay_seconds": perf_counter() - before,
            }
        )
        print(
            f"reduced {variant}: {record['complexity_before']} -> {record['complexity_after']}; replay={replay['matched']}",
            flush=True,
        )
    summary = summarize(rows, temporal_rows)
    output = {
        "manifest": manifest,
        "rows": rows,
        "temporal_rows": temporal_rows,
        "reproducers": reproducers,
        "summary": summary,
        "costs": costs,
        "timings": {
            "snapshot_seconds": snapshot_seconds,
            "temporal_seconds": temporal_seconds,
            "total_seconds": perf_counter() - started,
        },
    }
    write_json(args.output_dir / "results.json", output)
    flat = [
        {
            "id": r["id"],
            "partition": r["partition"],
            "family": r["family"],
            "variant": r["variant"],
            "reference_passed": r["reference"]["passed"],
            "detected": r["detected"],
            "category": r["category"],
            "execution_adapter_solves": r["execution_adapter_solves"],
        }
        for r in rows
    ]
    pq.write_table(pa.Table.from_pylist(flat), args.output_dir / "outcomes.parquet")
    (args.output_dir / "SUMMARY.md").write_text(
        markdown(summary, costs, reproducers), encoding="utf-8"
    )
    if any(r["detected"] for r in rows if r["variant"].endswith("control")):
        raise RuntimeError("Correct-controller negative control produced a false detection")
    if any(r["outcomes"]["confirmed-control"]["detected"] for r in temporal_rows):
        raise RuntimeError("Confirmed tracker negative control violated the property")
    if any(not r["replay"]["matched"] for r in reproducers):
        raise RuntimeError("A retained defect did not strictly reproduce")
    print(
        json.dumps(
            {
                "snapshot_pairs": len(rows),
                "temporal_episodes": len(temporal_rows),
                "reproducers": len(reproducers),
                "costs": costs,
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
