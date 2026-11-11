"""Predetermined transfer checks and testing-utility measurements, no tuning loop.

Run: python experiments/run_verification_benchmark.py
Run the paired search benchmark first; this study also analyzes its signatures.
"""

import hashlib
import argparse
import json
import random
from collections import Counter
from pathlib import Path
from time import perf_counter
import pyarrow as pa
import pyarrow.parquet as pq
from gridsense.cases import PortableCase, ServiceContract
from gridsense.controllers import CONTROLLERS
from gridsense.domain import Scenario
from gridsense.plants import plant_for, planning_view
from gridsense.regression import evaluate_case, harness_hash
from gridsense.temporal import TemporalInput, run_temporal, replay_temporal
from gridsense.ieee13 import validate_reference
from gridsense.service import utc_now

DEST = Path(__file__).parent / "verification_results"
SEEDS = list(range(6))
POINTS = 8
GROUPS = [
    ("teaching", "feed_a", "development"),
    ("teaching", "seg_a", "transfer"),
    ("ieee13", "632670", "transfer"),
    ("ieee13", "671692", "transfer"),
]


def signature(result):
    return sorted({f"{v['kind']}:{v['element']}" for v in result["violations"]})


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, default=DEST)
    parser.add_argument(
        "--search-results", type=Path, default=Path(__file__).parent / "search_results/results.json"
    )
    args = parser.parse_args()
    destination = args.output_dir
    if destination.exists() and any(destination.iterdir()):
        parser.error("Output directory is not empty; choose a new directory")
    if not args.search_results.is_file():
        parser.error("Search results are missing; run run_search_benchmark.py first")
    started = utc_now()
    rows = []
    cases = []
    for feeder, fault, role in GROUPS:
        for seed in SEEDS:
            rng = random.Random(seed)
            start = perf_counter()
            for index in range(POINTS):
                if feeder == "teaching":
                    actual = round(rng.uniform(0.6, 1.9), 2)
                    reported = round(rng.uniform(0.6, 1.4), 2)
                    s = Scenario(
                        load_a=round(rng.uniform(0.75, 1.25), 2),
                        load_b=actual,
                        reported_b=reported,
                        load_c=round(rng.uniform(0.6, 1.6), 2),
                        uncertainty_pct=40,
                    )
                    restored = (1000 if fault == "feed_a" else 600) * s.load_a
                    critical = 400 * s.load_a
                else:
                    actual = round(rng.uniform(0.65, 1.1), 2)
                    reported = round(rng.uniform(0.65, 1.05), 2)
                    s = Scenario(
                        load_a=actual, load_b=reported, reported_b=reported, uncertainty_pct=20
                    )
                    restored = (2666 if fault == "632670" else 1013) * actual
                    critical = 485 * actual
                case = PortableCase(
                    title=f"{feeder}/{fault} seed{seed} point{index}",
                    feeder=feeder,
                    fault=fault,
                    scenario=s,
                    contract=ServiceContract(
                        minimum_restored_kw=0.95 * restored, minimum_critical_kw=0.95 * critical
                    ),
                    origin="Predetermined transfer protocol; no controller tuning on these results",
                )
                plant = plant_for(case)
                view = planning_view(plant, "2026-01-01T12:00:00+00:00")
                before = plant.solve(plant.truth)
                actual_branches = [
                    plant.execute(plant.truth, c.action).result for c in view.candidates
                ]
                attainable = any(
                    r.feasible
                    and r.restored_kw + 0.1 >= case.contract.minimum_restored_kw
                    and r.critical_served_kw + 0.1 >= case.contract.minimum_critical_kw
                    for r in actual_branches
                )
                inside = (
                    reported * (1 - s.uncertainty_pct / 100)
                    <= actual
                    <= reported * (1 + s.uncertainty_pct / 100)
                )
                cases.append(case.model_dump(mode="json"))
                for name, controller in CONTROLLERS.items():
                    r = evaluate_case(case, controller, plant=plant, view=view)
                    if not before.feasible:
                        category = "pre_existing_violation"
                    elif r["passed"]:
                        category = "contract_met"
                    elif not attainable:
                        category = "restoration_infeasible_in_action_space"
                    elif name == "hold-v1":
                        category = "deliberate_service_negative_control"
                    elif not inside:
                        category = "assumption_breach"
                    elif not r["electrical_pass"]:
                        category = "information_limited_electrical_violation"
                    else:
                        category = "service_shortfall_under_partial_information"
                    rows.append(
                        {
                            "feeder": feeder,
                            "fault": fault,
                            "role": role,
                            "seed": seed,
                            "point": index,
                            "controller": name,
                            "action": r["action"]["id"],
                            "category": category,
                            "attainable_with_truth": attainable,
                            "inside_assumed_range": inside,
                            "electrical_pass": r["electrical_pass"],
                            "service_pass": r["service_pass"],
                            "passed": r["passed"],
                            "restored_kw": r["result"]["restored_kw"],
                            "critical_served_kw": r["result"]["critical_served_kw"],
                            "max_loading_pct": r["result"]["max_loading_pct"],
                            "signature": signature(r["result"]),
                        }
                    )
            print(
                f"{feeder}/{fault} seed={seed} {POINTS} cases ({perf_counter() - start:.2f}s)",
                flush=True,
            )
    old = json.loads(args.search_results.read_text())
    utility = []
    for run in old["runs"]:
        signatures = set()
        for trial in run["trace"]:
            if trial["is_failure"]:
                shape = tuple(sorted({(v["kind"], v["element"]) for v in trial["violations"]}))
                signatures.add((trial["action"], trial["truth_inside_assumed_range"], shape))
        utility.append(
            {
                "policy": run["request"]["policy"],
                "scope": run["request"]["assumption_scope"],
                "seed": run["request"]["seed"],
                "method": run["strategy"],
                "first_failure_evaluation": run["first_failure_evaluation"],
                "evaluations": run["evaluations"],
                "failing_scenarios": run["failing_scenarios"],
                "observed_signature_count": len(signatures),
            }
        )
    temporal = []
    for seed in SEEDS:
        start = perf_counter()
        r = run_temporal(TemporalInput(seed=seed, budget=12))
        temporal.append(
            {
                "seed": seed,
                "first_failure_evaluation": next(
                    (t["evaluation"] for t in r["trials"] if t["is_failure"]), None
                ),
                "search_evaluations": len(r["trials"]),
                "reduction_evaluations": r["reduction"]["evaluations"] if r["reduction"] else 0,
                "reduced_events": r["reduced"]["events"] if r["reduced"] else None,
                "strict_replay_matched": replay_temporal(r)["matched"] if r["original"] else None,
                "elapsed_seconds": perf_counter() - start,
            }
        )
    summary = []
    for feeder, fault, role in GROUPS:
        for controller in CONTROLLERS:
            group = [
                r
                for r in rows
                if (r["feeder"], r["fault"], r["controller"]) == (feeder, fault, controller)
            ]
            summary.append(
                {
                    "feeder": feeder,
                    "fault": fault,
                    "role": role,
                    "controller": controller,
                    "cases": len(group),
                    "electrical_passes": sum(r["electrical_pass"] for r in group),
                    "contract_passes": sum(r["passed"] for r in group),
                    "categories": dict(Counter(r["category"] for r in group)),
                }
            )
    manifest = {
        "started_at": started,
        "finished_at": utc_now(),
        "harness_sha256": harness_hash(),
        "benchmark_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "seeds": SEEDS,
        "points_per_seed_group": POINTS,
        "groups": GROUPS,
        "search_artifact_sha256": hashlib.sha256(args.search_results.read_bytes()).hexdigest(),
        "protocol": "Paired random cases for all three controllers. Transfer groups excluded from controller development; electrical integration smoke checks were performed before this benchmark. This is not a blind external holdout. No model fitting or parameter tuning.",
        "limitations": [
            "Signature diversity counts observed constraint/element/action combinations, not distinct defects.",
            "Temporal fixture tests one intentionally seeded state-machine defect; repeated seeds do not create new mechanisms.",
            "Actual-demand reference is privileged and only labels attainability; it is not a competing equally informed controller.",
            "Finite uncertainty samples, two small networks and two fault positions each cannot establish operational safety or field generalization.",
            "The supplied paired search results are analyzed without treating their reanalysis as an independent discovery experiment.",
        ],
    }
    result = {
        "manifest": manifest,
        "reference_validation": validate_reference(),
        "summary": summary,
        "search_usefulness": utility,
        "temporal_usefulness": temporal,
        "cases": cases,
        "rows": rows,
    }
    destination.mkdir(parents=True, exist_ok=True)
    (destination / "results.json").write_text(json.dumps(result, indent=2, allow_nan=False) + "\n")
    pq.write_table(
        pa.Table.from_pylist(rows).replace_schema_metadata(
            {b"gridsense_manifest": json.dumps(manifest).encode()}
        ),
        destination / "outcomes.parquet",
    )
    lines = [
        "# Verification benchmark",
        "",
        f"{len(cases)} portable cases; {len(rows)} controller outcomes; seeds 0–5.",
        "",
        "| Feeder / fault | Group | Controller | Electrical passes | Full contract passes |",
        "|---|---|---|---:|---:|",
    ]
    for r in summary:
        lines.append(
            f"| {r['feeder']} / {r['fault']} | {r['role']} | {r['controller']} | {r['electrical_passes']}/{r['cases']} | {r['contract_passes']}/{r['cases']} |"
        )
    lines += [
        "",
        manifest["protocol"],
        "",
        "A pass requires service and electrical checks. Pre-existing violations and cases with no feasible restoration remain in the denominator and are classified separately in results.json.",
        "",
        "Directed vs random: the fixed search study does not establish earlier discovery by directed search. See search_results/SUMMARY.md. The per-run signature counts here measure clustering; they are not a bug count.",
        "",
        "| Temporal seed | First failure / 12 | Reduction evaluations | Reproduced |",
        "|---|---:|---:|---|",
    ]
    for r in temporal:
        lines.append(
            f"| {r['seed']} | {r['first_failure_evaluation']} | {r['reduction_evaluations']} | {r['strict_replay_matched']} |"
        )
    lines += ["", *manifest["limitations"], ""]
    (destination / "SUMMARY.md").write_text("\n".join(lines))


if __name__ == "__main__":
    main()
