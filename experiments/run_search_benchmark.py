"""Fixed search comparison. No seed selection, early stopping, or tuning on results.

Run from the project root: python experiments/run_search_benchmark.py
Every method gets 24 complete incident evaluations per seed. This is a small
descriptive benchmark on one synthetic feeder, not a deployment risk estimate.
"""

import hashlib
import itertools
import argparse
import json
import multiprocessing
import platform
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path
from statistics import mean

import pyarrow as pa
import pyarrow.parquet as pq
from gridsense import __version__
from gridsense.domain import Scenario
from gridsense.electrical import ElectricalEngine
from gridsense.failure_search import FIXED_AT, SearchInput, discover, search_hash
from gridsense.network import load_network
from gridsense.service import evaluate, implementation_hash, utc_now

SEEDS = tuple(range(6))
BUDGET = 24
DESTINATION = Path(__file__).resolve().parent / "search_results"


def run_pair(request):
    methods = ("directed", "random") if request.seed % 2 == 0 else ("random", "directed")
    return [discover(request, method)[0] for method in methods]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, default=DESTINATION)
    args = parser.parse_args()
    destination = args.output_dir
    if destination.exists() and any(destination.iterdir()):
        parser.error("Output directory is not empty; choose a new directory")
    started = utc_now()
    # Explicit warm-up, outside every method's discovery budget.
    evaluate(Scenario(), FIXED_AT)
    runs, rows = [], []
    for policy, scope, seed in itertools.product(
        ("nominal", "guarded"), ("inside", "unrestricted"), SEEDS
    ):
        request = SearchInput(
            policy=policy, assumption_scope=scope, seed=seed, budget=BUDGET, reduction_budget=0
        )
        # A fresh process releases native contexts after each fixed seed pair.
        with ProcessPoolExecutor(
            max_workers=1, mp_context=multiprocessing.get_context("spawn")
        ) as worker:
            pair = worker.submit(run_pair, request).result()
        for result in pair:
            method = result["strategy"]
            runs.append({"request": request.model_dump(), **result})
            print(
                f"{policy:7} {scope:12} seed={seed} {method:8} first={result['first_failure_evaluation']} failures={result['failing_scenarios']}/{result['evaluations']}",
                flush=True,
            )
            for row in result["trace"]:
                rows.append(
                    {
                        "policy": policy,
                        "scope": scope,
                        "seed": seed,
                        "method": method,
                        "evaluation": row["evaluation"],
                        **row["point"],
                        "category": row["category"],
                        "action": row["action"],
                        "is_failure": row["is_failure"],
                        "inside_assumed_range": row["truth_inside_assumed_range"],
                        "actual_loading_pct": row["actual_loading_pct"],
                        "predicted_loading_pct": row["predicted_loading_pct"],
                        "score": row["score"],
                        "violations_json": json.dumps(row["violations"], sort_keys=True),
                    }
                )
    summary = []
    for policy, scope, method in itertools.product(
        ("nominal", "guarded"), ("inside", "unrestricted"), ("directed", "random")
    ):
        group = [
            r
            for r in runs
            if r["request"]["policy"] == policy
            and r["request"]["assumption_scope"] == scope
            and r["strategy"] == method
        ]
        hits = [r for r in group if r["first_failure_evaluation"] is not None]
        summary.append(
            {
                "policy": policy,
                "scope": scope,
                "method": method,
                "successful_runs": len(hits),
                "runs": len(group),
                "mean_capped_first_failure": mean(
                    r["first_failure_evaluation"] or BUDGET + 1 for r in group
                ),
                "mean_first_failure_among_hits": mean(r["first_failure_evaluation"] for r in hits)
                if hits
                else None,
                "mean_elapsed_seconds": mean(r["elapsed_seconds"] for r in group),
                "failing_trials": sum(r["failing_scenarios"] for r in group),
                "total_trials": sum(r["evaluations"] for r in group),
            }
        )
    paired = []
    for policy, scope, seed in itertools.product(
        ("nominal", "guarded"), ("inside", "unrestricted"), SEEDS
    ):
        group = {
            r["strategy"]: r
            for r in runs
            if r["request"]["policy"] == policy
            and r["request"]["assumption_scope"] == scope
            and r["request"]["seed"] == seed
        }
        values = {k: r["first_failure_evaluation"] or BUDGET + 1 for k, r in group.items()}
        winner = "tie" if values["directed"] == values["random"] else min(values, key=values.get)
        paired.append(
            {"policy": policy, "scope": scope, "seed": seed, "earlier_method": winner, **values}
        )
    manifest = {
        "app_version": __version__,
        "started_at": started,
        "finished_at": utc_now(),
        "python": platform.python_version(),
        "platform": platform.platform(),
        "solver_version": ElectricalEngine().version,
        "network": load_network(),
        "core_implementation_sha256": implementation_hash(),
        "search_implementation_sha256": search_hash(),
        "benchmark_script_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "seeds": list(SEEDS),
        "budget_per_method": BUDGET,
        "evaluation_at": FIXED_AT,
        "execution": "Sequential fresh worker per paired seed. Method times exclude process startup; total campaign time includes it. Native contexts are released at process exit.",
        "methodology": "Paired seeds, identical admissible 0.05 grid, same complete-incident budget, no repeated point within a method. First four points match. Alternate method order by seed. One unscored warm-up. No reduction costs included.",
        "censoring": "A run without a failure is assigned budget+1 (25) only for the explicitly capped first-failure metric and paired comparison. It is not an observed discovery time.",
        "limits": "Six predetermined seeds per condition. One custom feeder and one fault location. Correlated failing scenarios are not distinct defects. Searcher sees simulator truth; controllers do not. No search result establishes field safety, calibrated risk, or research novelty.",
    }
    destination.mkdir(parents=True, exist_ok=True)
    result = {"manifest": manifest, "summary": summary, "paired_comparison": paired, "runs": runs}
    (destination / "results.json").write_text(json.dumps(result, indent=2, allow_nan=False) + "\n")
    table = pa.Table.from_pylist(rows).replace_schema_metadata(
        {b"gridsense_manifest": json.dumps(manifest).encode()}
    )
    pq.write_table(table, destination / "trials.parquet")
    lines = [
        "# Failure-search benchmark",
        "",
        f"{len(rows)} complete incident evaluations; {len(runs)} method runs; {BUDGET} trials per method; seeds 0–5.",
        "",
        "| Controller | Scope | Method | Runs finding failure | Mean capped first trial ↓ | Failing trials | Mean run seconds |",
        "|---|---|---|---:|---:|---:|---:|",
    ]
    for row in summary:
        lines.append(
            f"| {row['policy']} | {row['scope']} | {row['method']} | {row['successful_runs']}/{row['runs']} | {row['mean_capped_first_failure']:.2f} | {row['failing_trials']}/{row['total_trials']} | {row['mean_elapsed_seconds']:.2f} |"
        )
    lines += [
        "",
        manifest["censoring"],
        "",
        manifest["methodology"],
        "",
        manifest["limits"],
        "",
        "Timing is environment dependent. Compare budgets and paired discovery outcomes first. Do not treat failing-trial counts as a utility failure probability. Inspect every seed, including no-hit runs, in results.json; trials.parquet contains all evaluated points and provenance metadata.",
        "",
    ]
    (destination / "SUMMARY.md").write_text("\n".join(lines))


if __name__ == "__main__":
    main()
