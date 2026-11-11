"""Compare native reuse with a full-demand-key reference on frozen planning inputs."""

import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from time import perf_counter
from unittest.mock import patch

from gridsense.electrical import ElectricalEngine
from gridsense.episodes import canonical_hash, episode_hash
from gridsense.network import load_network
from gridsense.restoration import PlanningView, Predictor, demand_samples, plan
from gridsense.service import _differences
from native_reuse_reference import FullDemandPredictor

ROOT = Path(__file__).resolve().parents[1]
PROTOCOL = ROOT / "experiments/protocols/native_reuse.json"
FREEZE = PROTOCOL.with_suffix(".freeze.json")


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write(path, value):
    path.write_text(json.dumps(value, indent=2, allow_nan=False) + "\n", encoding="utf-8")


def fingerprints():
    return {
        "episode_sha256": episode_hash(),
        "protocol_sha256": digest(PROTOCOL),
        "runner_sha256": digest(Path(__file__)),
        "reference_sha256": digest(ROOT / "experiments/native_reuse_reference.py"),
    }


class CountedEngine(ElectricalEngine):
    def __init__(self):
        super().__init__()
        self.calls = 0

    def solve(self, state):
        self.calls += 1
        return super().solve(state)


def checked_protocol():
    protocol = json.loads(PROTOCOL.read_text(encoding="utf-8"))
    ids = [case["id"] for case in protocol["cases"]]
    if len(ids) != len(set(ids)) or len(ids) != 8 or protocol["budgets"] != [192, 2048]:
        raise ValueError("Frozen case identities or budgets differ")
    for case in protocol["cases"]:
        PlanningView.model_validate(case["view"])
    return protocol


def comparison(reference, reused, tolerance):
    complete = reference["search_complete"] and reused["search_complete"]
    fields = ("feasible_choice", "selected")
    differences = _differences(
        {key: reference[key] for key in fields},
        {key: reused[key] for key in fields},
        tolerance=tolerance,
    )
    return {"both_searches_complete": complete, "differences": differences}


def summarize(rows):
    return {
        "planning_pairs": len(rows),
        "complete_pairs": sum(r["comparison"]["both_searches_complete"] for r in rows),
        "complete_search_mismatches": sum(
            r["comparison"]["both_searches_complete"] and bool(r["comparison"]["differences"])
            for r in rows
        ),
        "native_calls": {
            name: sum(r[name]["native_evaluations"] for r in rows)
            for name in ("full_demand", "reused")
        },
        "budget_exhausted": {
            name: sum(r[name]["budget_exhausted"] for r in rows)
            for name in ("full_demand", "reused")
        },
        "no_feasible_choice": {
            name: sum(not r[name]["feasible_choice"] for r in rows)
            for name in ("full_demand", "reused")
        },
    }


def verify(directory):
    protocol = checked_protocol()
    freeze = json.loads(FREEZE.read_text(encoding="utf-8"))
    report = json.loads((directory / "results.json").read_text(encoding="utf-8"))
    if (
        report["fingerprints"] != fingerprints()
        or freeze["fingerprints"] != fingerprints()
        or report["freeze"] != freeze
        or report["protocol"] != protocol
        or report["content_sha256"]
        != canonical_hash({k: v for k, v in report.items() if k != "content_sha256"})
    ):
        raise ValueError("Source, protocol, freeze or report integrity differs")
    if len(report["probes"]) != len(protocol["cases"]):
        raise ValueError("Incomplete native equivalence comparison")
    for case, probe in zip(protocol["cases"], report["probes"], strict=True):
        view = PlanningView.model_validate(case["view"])
        samples = demand_samples(view, "guarded")
        if probe["case"] != case["id"] or len(probe["outcomes"]) != len(samples):
            raise ValueError("Probe identities or denominator differ")
        for sample, outcome in zip(samples, probe["outcomes"], strict=True):
            expected_request = sum(
                sample[load["id"]] * view.state.load_factors[load["feeder"]]
                for load in load_network()["loads"]
            )
            if (
                outcome["demand_kw"] != sample
                or _differences(
                    outcome["full_demand"],
                    outcome["reused"],
                    tolerance=protocol["comparison_tolerance"],
                )
                or abs(outcome["reused"]["requested_kw"] - expected_request) > 1e-9
            ):
                raise ValueError("Native prediction or disconnected-demand accounting differs")
    expected = [(c["id"], b) for c in protocol["cases"] for b in protocol["budgets"]]
    if [(r["case"], r["budget"]) for r in report["rows"]] != expected:
        raise ValueError("Incomplete or reordered planning comparison")
    for row in report["rows"]:
        if row["comparison"] != comparison(
            row["full_demand"], row["reused"], protocol["comparison_tolerance"]
        ):
            raise ValueError("Recorded comparison differs")
        for name in ("full_demand", "reused"):
            if row[name]["native_evaluations"] != row[name]["counted_adapter_calls"]:
                raise ValueError("Native-call counter differs from instrumented adapter calls")
            if row[name]["native_evaluations"] > row["budget"]:
                raise ValueError("Planning exceeded the public native-call budget")
    summary = summarize(report["rows"])
    if report["summary"] != summary or summary["complete_search_mismatches"]:
        raise ValueError("Summary or a completed search differs")
    return {"source_and_accounting_verified": True, **summary}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output-dir", type=Path, default=ROOT / "experiments/native_reuse_results"
    )
    parser.add_argument("--freeze", action="store_true")
    parser.add_argument("--verify-report", action="store_true")
    args = parser.parse_args()
    protocol = checked_protocol()
    if args.freeze:
        if FREEZE.exists():
            parser.error("Freeze already exists; preserve it")
        write(
            FREEZE,
            {"frozen_at": datetime.now(timezone.utc).isoformat(), "fingerprints": fingerprints()},
        )
        print(json.dumps({"freeze": str(FREEZE), "cases": len(protocol["cases"])}))
        return
    if args.verify_report:
        print(json.dumps(verify(args.output_dir), indent=2))
        return
    freeze = json.loads(FREEZE.read_text(encoding="utf-8"))
    if freeze["fingerprints"] != fingerprints():
        parser.error("Frozen source or inputs differ")
    if args.output_dir.exists() and any(args.output_dir.iterdir()):
        parser.error("Use a new empty output directory")
    args.output_dir.mkdir(parents=True, exist_ok=True)
    engine = CountedEngine()
    probes, rows = [], []
    started_at = datetime.now(timezone.utc).isoformat()
    for index, case in enumerate(protocol["cases"]):
        view = PlanningView.model_validate(case["view"])
        reference = FullDemandPredictor(view, "guarded", 100, engine)
        reused = Predictor(view, "guarded", 100, engine)
        outcomes = [
            {
                "demand_kw": sample,
                "full_demand": reference._solve(view.state, sample),
                "reused": reused._solve(view.state, sample),
            }
            for sample in demand_samples(view, "guarded")
        ]
        probes.append(
            {
                "case": case["id"],
                "outcomes": outcomes,
                "native_calls": {"full_demand": reference.solves, "reused": reused.solves},
            }
        )
        for budget in protocol["budgets"]:
            pair = {"case": case["id"], "budget": budget}
            order = ("full_demand", "reused") if index % 2 == 0 else ("reused", "full_demand")
            for name in order:
                before, started = engine.calls, perf_counter()
                with patch(
                    "gridsense.restoration.Predictor",
                    FullDemandPredictor if name == "full_demand" else Predictor,
                ):
                    proposal = plan(
                        view,
                        "guarded",
                        budget=budget,
                        max_operations=case["max_operations"],
                        engine=engine,
                    )
                pair[name] = {
                    key: proposal[key]
                    for key in (
                        "feasible_choice",
                        "selected",
                        "search_complete",
                        "budget_exhausted",
                        "native_evaluations",
                        "native_cache_hits",
                        "structural_sequences",
                        "service_bound_pruned",
                    )
                }
                pair[name].update(
                    counted_adapter_calls=engine.calls - before,
                    wall_seconds=perf_counter() - started,
                )
            pair["comparison"] = comparison(
                pair["full_demand"], pair["reused"], protocol["comparison_tolerance"]
            )
            rows.append(pair)
            print(
                json.dumps(
                    {
                        "case": case["id"],
                        "budget": budget,
                        "native_calls": {
                            n: pair[n]["native_evaluations"] for n in ("full_demand", "reused")
                        },
                        "comparison": pair["comparison"],
                    }
                ),
                flush=True,
            )
    if freeze["fingerprints"] != fingerprints():
        raise ValueError("Source changed during execution")
    report = {
        "started_at": started_at,
        "completed_at": datetime.now(timezone.utc).isoformat(),
        "solver_version": engine.version,
        "protocol": protocol,
        "freeze": freeze,
        "fingerprints": fingerprints(),
        "probes": probes,
        "rows": rows,
        "summary": summarize(rows),
        "scope": "Frozen synthetic planning comparison on one host, sharing native physics and the objective. Complete-search equivalence and computation are assessed; this is not physical field validation or a general restoration-performance guarantee. Wall times are single runs with alternated implementation order.",
    }
    report["content_sha256"] = canonical_hash(report)
    write(args.output_dir / "results.json", report)
    print(json.dumps(verify(args.output_dir), indent=2))


if __name__ == "__main__":
    main()
