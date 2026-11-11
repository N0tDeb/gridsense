"""Run the fixed-seed protocol without changing controllers or search settings.

python experiments/run_quality_benchmark.py
Measurement wrappers count adapter solve calls; they do not alter decisions
or source files. Existing outputs are never overwritten.
"""

import argparse
import hashlib
import itertools
import json
import multiprocessing
import platform
import random
from collections import Counter
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path
from time import perf_counter
from unittest.mock import patch

import numpy as np
import pyarrow as pa
import pyarrow.parquet as pq
from gridsense import __version__
from gridsense import failure_search as fs
from gridsense.cases import PortableCase, ServiceContract
from gridsense.controllers import CONTROLLERS
from gridsense.domain import Scenario
from gridsense.electrical import ElectricalEngine
from gridsense.plants import plant_for, planning_view
from gridsense.regression import evaluate_case, harness_hash
from gridsense.service import evaluate, implementation_hash, utc_now

ROOT = Path(__file__).resolve().parent
PROTOCOL = ROOT / "protocols/quality.json"
PROTOCOL_SHA256 = "5ca697da36b757cbdfd8dc1e0353ffa1e3157ce1ce92bdff84c7022527de8e59"


def write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    temporary.replace(path)


class SolveMeter:
    """Count complete teaching-adapter calls, not DSS internal iterations."""

    def __init__(self):
        self.calls = 0

    def instrument(self):
        original = ElectricalEngine.solve

        def measured(engine, *args, **kwargs):
            self.calls += 1
            return original(engine, *args, **kwargs)

        return patch.object(ElectricalEngine, "solve", measured)


def measured_search(request):
    meter = SolveMeter()
    costs = {}
    discover, reduce_case, incident_evaluate = fs.discover, fs.reduce_case, fs.evaluate

    def discovery(req, method, at):
        begin = meter.calls
        cumulative = []

        def evaluate_and_count(*args, **kwargs):
            value = incident_evaluate(*args, **kwargs)
            cumulative.append(meter.calls - begin)
            return value

        with patch.object(fs, "evaluate", evaluate_and_count):
            result = discover(req, method, at)
        first = result[0]["first_failure_evaluation"]
        costs[method] = {
            "electrical_adapter_evaluations": meter.calls - begin,
            "cumulative_adapter_evaluations": cumulative,
            "adapter_evaluations_to_first_failure": cumulative[first - 1] if first else None,
        }
        return result

    def reduction(req, original):
        begin, start = meter.calls, perf_counter()
        result = reduce_case(req, original)
        costs["reduction"] = {
            "electrical_adapter_evaluations": meter.calls - begin,
            "elapsed_seconds": perf_counter() - start,
        }
        return result

    with (
        meter.instrument(),
        patch.object(fs, "discover", discovery),
        patch.object(fs, "reduce_case", reduction),
    ):
        record = fs.run_search(request)
        # Reproduction is budgeted and measured separately from both searches.
        if record["original_incident"] and request.reduction_budget:
            begin, start = meter.calls, perf_counter()
            result = fs.replay_search(record)
            costs["replay"] = {
                "electrical_adapter_evaluations": meter.calls - begin,
                "elapsed_seconds": perf_counter() - start,
                **result,
            }
            if not result["matched"]:
                raise RuntimeError("A retained failure did not reproduce")
    return record, costs


def isolated_call(function, *args):
    """Sequential job in a fresh process, releasing native contexts at exit."""
    with ProcessPoolExecutor(
        max_workers=1, mp_context=multiprocessing.get_context("spawn")
    ) as worker:
        return worker.submit(function, *args).result()


def controller_group(protocol, feeder, fault, seed):
    cases, rows = [], []
    rng = random.Random(seed)
    start = perf_counter()
    for point in range(protocol["controller_points_per_seed_group"]):
        # Declared generator and contracts; seed groups stay fixed.
        if feeder == "teaching":
            actual, reported = (
                round(rng.uniform(0.6, 1.9), 2),
                round(rng.uniform(0.6, 1.4), 2),
            )
            scenario = Scenario(
                load_a=round(rng.uniform(0.75, 1.25), 2),
                load_b=actual,
                reported_b=reported,
                load_c=round(rng.uniform(0.6, 1.6), 2),
                uncertainty_pct=40,
            )
            restored, critical = (
                (1000 if fault == "feed_a" else 600) * scenario.load_a,
                400 * scenario.load_a,
            )
        else:
            actual, reported = (
                round(rng.uniform(0.65, 1.1), 2),
                round(rng.uniform(0.65, 1.05), 2),
            )
            scenario = Scenario(
                load_a=actual, load_b=reported, reported_b=reported, uncertainty_pct=20
            )
            restored, critical = (
                (2666 if fault == "632670" else 1013) * actual,
                485 * actual,
            )
        case = PortableCase(
            title=f"{feeder}/{fault} seed{seed} point{point}",
            feeder=feeder,
            fault=fault,
            scenario=scenario,
            contract=ServiceContract(
                minimum_restored_kw=0.95 * restored, minimum_critical_kw=0.95 * critical
            ),
            origin="Fixed-seed protocol; evaluation on known models; no tuning",
        )
        plant = plant_for(case)
        view = planning_view(plant, fs.FIXED_AT)
        before = plant.solve(plant.truth)
        branches = [plant.execute(plant.truth, c.action).result for c in view.candidates]
        attainable = any(
            r.feasible
            and r.restored_kw + 0.1 >= case.contract.minimum_restored_kw
            and r.critical_served_kw + 0.1 >= case.contract.minimum_critical_kw
            for r in branches
        )
        inside = (
            reported * (1 - scenario.uncertainty_pct / 100)
            <= actual
            <= reported * (1 + scenario.uncertainty_pct / 100)
        )
        case_id = f"{feeder}-{fault}-{seed}-{point}"
        cases.append(
            {
                "case_id": case_id,
                "case": case.model_dump(mode="json"),
                "initially_feasible": before.feasible,
                "attainable_with_truth": attainable,
                "truth_alternatives": [
                    {
                        "action": c.action.id,
                        "feasible": r.feasible,
                        "restored_kw": r.restored_kw,
                        "critical_served_kw": r.critical_served_kw,
                    }
                    for c, r in zip(view.candidates, branches)
                ],
            }
        )
        for name, controller in CONTROLLERS.items():
            result = evaluate_case(case, controller, plant=plant, view=view)
            if not before.feasible:
                category = "pre_existing_violation"
            elif result["passed"]:
                category = "contract_met"
            elif not attainable:
                category = "restoration_infeasible_in_action_space"
            elif name == "hold-v1":
                category = "deliberate_service_negative_control"
            elif not inside:
                category = "assumption_breach"
            elif not result["electrical_pass"]:
                category = "information_limited_electrical_violation"
            else:
                category = "service_shortfall_under_partial_information"
            rows.append(
                {
                    "case_id": case_id,
                    "feeder": feeder,
                    "fault": fault,
                    "seed": seed,
                    "point": point,
                    "controller": name,
                    "action": result["action"]["id"],
                    "category": category,
                    "initially_feasible": before.feasible,
                    "attainable_with_truth": attainable,
                    "eligible": before.feasible and attainable,
                    "inside_assumed_range": inside,
                    "electrical_pass": result["electrical_pass"],
                    "service_pass": result["service_pass"],
                    "passed": result["passed"],
                    "restored_kw": result["result"]["restored_kw"],
                    "critical_served_kw": result["result"]["critical_served_kw"],
                    "unserved_kw": result["result"]["unserved_kw"],
                    "max_loading_pct": result["result"]["max_loading_pct"],
                    "violations_json": json.dumps(result["result"]["violations"], sort_keys=True),
                }
            )
    return cases, rows, perf_counter() - start


def paired_interval(clusters, rng, samples):
    """Bootstrap whole paired seeds, retaining each seed's numerator/denominator."""
    values = np.asarray(clusters, dtype=float)
    if values[:, 1].sum() == 0:
        return {"difference": None, "ci95": None, "seeds": len(clusters), "valid_resamples": 0}
    draws = values[rng.integers(0, len(values), size=(samples, len(values)))].sum(axis=1)
    valid = draws[:, 1] > 0
    ratios = draws[valid, 0] / draws[valid, 1]
    return {
        "difference": float(values[:, 0].sum() / values[:, 1].sum()),
        "ci95": [float(x) for x in np.quantile(ratios, [0.025, 0.975])],
        "seeds": len(clusters),
        "valid_resamples": int(valid.sum()),
    }


def summaries(protocol, runs, rows):
    rng = np.random.default_rng(protocol["bootstrap_seed"])
    samples, budget = protocol["bootstrap_samples"], protocol["search_budget_per_method"]
    search, paired = [], []
    for policy, scope in itertools.product(("nominal", "guarded"), ("inside", "unrestricted")):
        group = [r for r in runs if r["policy"] == policy and r["scope"] == scope]
        for method in ("directed", "random"):
            chosen = [r for r in group if r["method"] == method]
            search.append(
                {
                    "policy": policy,
                    "scope": scope,
                    "method": method,
                    "runs": len(chosen),
                    "hits": sum(r["first_failure_evaluation"] is not None for r in chosen),
                    "mean_capped_first_failure": float(
                        np.mean([r["first_failure_evaluation"] or budget + 1 for r in chosen])
                    ),
                    "electrical_adapter_evaluations": sum(
                        r["cost"]["electrical_adapter_evaluations"] for r in chosen
                    ),
                    "elapsed_seconds": sum(r["elapsed_seconds"] for r in chosen),
                    "failing_trials": sum(r["failing_scenarios"] for r in chosen),
                    "trials": sum(r["evaluations"] for r in chosen),
                }
            )
        clusters = []
        hit_clusters = []
        winners = Counter()
        for seed in protocol["search_seeds"]:
            pair = {r["method"]: r for r in group if r["seed"] == seed}
            delta = (pair["directed"]["first_failure_evaluation"] or budget + 1) - (
                pair["random"]["first_failure_evaluation"] or budget + 1
            )
            clusters.append((delta, 1))
            hit_clusters.append(
                (
                    int(pair["directed"]["first_failure_evaluation"] is not None)
                    - int(pair["random"]["first_failure_evaluation"] is not None),
                    1,
                )
            )
            winners["directed" if delta < 0 else "random" if delta > 0 else "tie"] += 1
        paired.append(
            {
                "policy": policy,
                "scope": scope,
                "direction": "directed minus random",
                "capped_first_failure": paired_interval(clusters, rng, samples),
                "hit_rate": paired_interval(hit_clusters, rng, samples),
                "earlier_counts": dict(winners),
            }
        )
    controllers, tradeoffs = [], []
    for feeder, fault in protocol["controller_groups"]:
        group = [r for r in rows if r["feeder"] == feeder and r["fault"] == fault]
        for name in CONTROLLERS:
            chosen = [r for r in group if r["controller"] == name]
            eligible = [r for r in chosen if r["eligible"]]
            controllers.append(
                {
                    "feeder": feeder,
                    "fault": fault,
                    "controller": name,
                    "cases": len(chosen),
                    "electrical_passes": sum(r["electrical_pass"] for r in chosen),
                    "service_passes": sum(r["service_pass"] for r in chosen),
                    "contract_passes": sum(r["passed"] for r in chosen),
                    "eligible_cases": len(eligible),
                    "eligible_electrical_passes": sum(r["electrical_pass"] for r in eligible),
                    "eligible_contract_passes": sum(r["passed"] for r in eligible),
                    "categories": dict(Counter(r["category"] for r in chosen)),
                }
            )
        for population in ("all", "eligible"):
            for metric in ("electrical_pass", "passed"):
                clusters = []
                for seed in protocol["controller_seeds"]:
                    chosen = [
                        r
                        for r in group
                        if r["seed"] == seed and (population == "all" or r["eligible"])
                    ]
                    nominal = [r for r in chosen if r["controller"] == "nominal-v1"]
                    guarded = [r for r in chosen if r["controller"] == "guarded-v1"]
                    clusters.append(
                        (
                            sum(r[metric] for r in guarded) - sum(r[metric] for r in nominal),
                            len(nominal),
                        )
                    )
                tradeoffs.append(
                    {
                        "feeder": feeder,
                        "fault": fault,
                        "population": population,
                        "metric": metric,
                        "direction": "guarded minus nominal pass-rate",
                        **paired_interval(clusters, rng, samples),
                    }
                )
    return {
        "search": search,
        "paired_search": paired,
        "controllers": controllers,
        "controller_tradeoffs": tradeoffs,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, default=ROOT / "quality_results")
    args = parser.parse_args()
    protocol_bytes = PROTOCOL.read_bytes()
    if hashlib.sha256(protocol_bytes).hexdigest() != PROTOCOL_SHA256:
        raise ValueError("Frozen protocol changed; do not silently redefine this experiment")
    protocol = json.loads(protocol_bytes)
    expected = (protocol["core_sha256"], protocol["search_sha256"], protocol["harness_sha256"])
    if expected != (implementation_hash(), fs.search_hash(), harness_hash()):
        raise ValueError("Current source does not match the frozen protocol")
    destination = args.output_dir
    if destination.exists() and any(destination.iterdir()):
        parser.error("Output directory is not empty; use a new directory")
    destination.mkdir(parents=True, exist_ok=True)
    manifest = {
        "app_version": __version__,
        "started_at": utc_now(),
        "protocol_sha256": PROTOCOL_SHA256,
        "protocol": protocol,
        "runner_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "python": platform.python_version(),
        "platform": platform.platform(),
        "solver_version": ElectricalEngine().version,
        "execution": "Sequential fresh worker for each paired search seed and controller seed-group; process exit releases retained native contexts. Method times exclude process startup; total campaign time includes it.",
        "cost_definition": "Calls to ElectricalEngine.solve, including preconditions and intermediate states. Not native solver iterations. Only search/reduction/replay costs are metered.",
        "interval_definition": "Paired whole-seed percentile bootstrap, NumPy default_rng, 10000 draws. No independence claim for trials within a seed. No multiple-comparison correction.",
        "limitations": [
            "New seeds on previously inspected small feeder models, not a blind external holdout.",
            "No controller, search, service threshold or uncertainty bound was tuned using these results.",
            "No-hit capped trial 17 is an administrative score, not an observed discovery time.",
            "Degenerate intervals do not establish equality or safety beyond this sample.",
            "Eligible means initially electrically feasible and service attainable within the bounded actions with privileged truth; all-case outcomes remain visible.",
            "Timings are sequential measurements on this machine, not portable speed guarantees.",
        ],
    }
    runs, trial_rows, reductions, cases, rows = [], [], [], [], []
    warmup = perf_counter()
    evaluate(Scenario(), fs.FIXED_AT)
    manifest["unscored_warmup_seconds"] = perf_counter() - warmup
    for policy, scope, seed in itertools.product(
        ("nominal", "guarded"), ("inside", "unrestricted"), protocol["search_seeds"]
    ):
        request = fs.SearchInput(
            policy=policy,
            assumption_scope=scope,
            seed=seed,
            budget=protocol["search_budget_per_method"],
            reduction_budget=protocol["reduction_budget"]
            if seed in protocol["reduction_seeds"]
            else 0,
        )
        record, costs = isolated_call(measured_search, request)
        for method, run in record["strategies"].items():
            runs.append(
                {
                    "policy": policy,
                    "scope": scope,
                    "seed": seed,
                    "method": method,
                    "request": record["request"],
                    "cost": costs[method],
                    **run,
                }
            )
            for i, trial in enumerate(run["trace"]):
                trial_rows.append(
                    {
                        "policy": policy,
                        "scope": scope,
                        "seed": seed,
                        "method": method,
                        "evaluation": trial["evaluation"],
                        **trial["point"],
                        "category": trial["category"],
                        "action": trial["action"],
                        "is_failure": trial["is_failure"],
                        "inside_assumed_range": trial["truth_inside_assumed_range"],
                        "actual_loading_pct": trial["actual_loading_pct"],
                        "predicted_loading_pct": trial["predicted_loading_pct"],
                        "cumulative_adapter_evaluations": costs[method][
                            "cumulative_adapter_evaluations"
                        ][i],
                        "violations_json": json.dumps(trial["violations"], sort_keys=True),
                    }
                )
        if seed in protocol["reduction_seeds"]:
            filename = f"{policy}-{scope}-seed{seed}.json"
            write_json(destination / "reproducers" / filename, record)
            reductions.append(
                {
                    "policy": policy,
                    "scope": scope,
                    "seed": seed,
                    "status": record["status"],
                    "selected_strategy": record["selected_strategy"],
                    "reproducer": "reproducers/" + filename,
                    "reduction": record["reduction"],
                    "reduction_cost": costs.get("reduction"),
                    "replay": costs.get("replay"),
                }
            )
        write_json(
            destination / "progress.json",
            {
                "manifest": manifest,
                "completed_search_runs": runs,
                "reductions": reductions,
                "cases": cases,
                "rows": rows,
            },
        )
        print(
            f"Search {policy}/{scope} seed={seed}: "
            + ", ".join(
                f"{k} first={v['first_failure_evaluation']}"
                for k, v in record["strategies"].items()
            ),
            flush=True,
        )
    for feeder, fault in protocol["controller_groups"]:
        for seed in protocol["controller_seeds"]:
            group_cases, group_rows, elapsed = isolated_call(
                controller_group, protocol, feeder, fault, seed
            )
            cases.extend(group_cases)
            rows.extend(group_rows)
            write_json(
                destination / "progress.json",
                {
                    "manifest": manifest,
                    "completed_search_runs": runs,
                    "reductions": reductions,
                    "cases": cases,
                    "rows": rows,
                },
            )
            print(
                f"Controllers {feeder}/{fault} seed={seed}: {protocol['controller_points_per_seed_group']} cases, {elapsed:.2f}s",
                flush=True,
            )
    summary = summaries(protocol, runs, rows)
    manifest["finished_at"] = utc_now()
    result = {
        "manifest": manifest,
        "summary": summary,
        "search_runs": runs,
        "reductions": reductions,
        "cases": cases,
        "controller_rows": rows,
    }
    write_json(destination / "results.json", result)
    for filename, data in (
        ("search_trials.parquet", trial_rows),
        ("controller_outcomes.parquet", rows),
    ):
        table = pa.Table.from_pylist(data).replace_schema_metadata(
            {b"gridsense_manifest": json.dumps(manifest).encode()}
        )
        pq.write_table(table, destination / filename)
    lines = [
        "# Fixed-protocol quality evaluation",
        "",
        f"{len(trial_rows)} complete search trials; {len(runs)} method runs; {len(cases)} controller cases; {len(rows)} controller outcomes.",
        "",
        "| Policy / scope | Method | Runs finding failure | Capped first trial | Adapter evaluations | Total seconds |",
        "|---|---|---:|---:|---:|---:|",
    ]
    for r in summary["search"]:
        lines.append(
            f"| {r['policy']} / {r['scope']} | {r['method']} | {r['hits']}/{r['runs']} | {r['mean_capped_first_failure']:.2f} | {r['electrical_adapter_evaluations']} | {r['elapsed_seconds']:.2f} |"
        )
    lines += [
        "",
        "Paired discovery difference is **directed minus random**; negative favors directed. No hit is capped at 17.",
        "",
        "| Policy / scope | Mean paired difference | Whole-seed bootstrap 95% interval |",
        "|---|---:|---|",
    ]
    for r in summary["paired_search"]:
        v = r["capped_first_failure"]
        lines.append(
            f"| {r['policy']} / {r['scope']} | {v['difference']:.2f} | [{v['ci95'][0]:.2f}, {v['ci95'][1]:.2f}] |"
        )
    lines += [
        "",
        "| Feeder / fault | Controller | Electrical pass | Full contract pass | Eligible contract pass |",
        "|---|---|---:|---:|---:|",
    ]
    for r in summary["controllers"]:
        eligible = (
            f"{r['eligible_contract_passes']}/{r['eligible_cases']}"
            if r["eligible_cases"]
            else "N/A (0 eligible)"
        )
        lines.append(
            f"| {r['feeder']} / {r['fault']} | {r['controller']} | {r['electrical_passes']}/{r['cases']} | {r['contract_passes']}/{r['cases']} | {eligible} |"
        )
    lines += [
        "",
        "Eligible = initially feasible and contract attainable in the bounded action set using privileged truth. All cases remain in the preceding columns.",
        "",
        "| Retained search | Status | Extra reduction trials | Extra adapter calls | Strict replay |",
        "|---|---|---:|---:|---|",
    ]
    for r in reductions:
        lines.append(
            f"| {r['policy']} / {r['scope']}, seed {r['seed']} | {r['status']} | {r['reduction']['evaluations'] if r['reduction'] else 0} | {r['reduction_cost']['electrical_adapter_evaluations'] if r['reduction_cost'] else 0} | {r['replay']['matched'] if r['replay'] else 'N/A: no failure'} |"
        )
    lines += [
        "",
        "Per-seed traces, paired hit-rate intervals, conditional controller intervals, case inputs, truth attainability and separate replay costs are retained in results.json. Both Parquet files include the same provenance manifest.",
        "",
        *[f"- {s}" for s in manifest["limitations"]],
        "",
        manifest["cost_definition"],
        "",
        manifest["interval_definition"],
        "",
    ]
    (destination / "SUMMARY.md").write_text("\n".join(lines), encoding="utf-8")
    (destination / "progress.json").unlink()
    print(f"Finished: {destination}/SUMMARY.md", flush=True)


if __name__ == "__main__":
    main()
