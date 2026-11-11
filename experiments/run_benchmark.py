"""Deterministic scenario grid; exports all outcomes, including failures.

No training occurs. This evaluates behavior on a custom feeder, not field validity.
Run from the project root with: python experiments/run_benchmark.py
"""

import argparse
import json
from pathlib import Path
import statistics
import pyarrow as pa
import pyarrow.parquet as pq
from gridsense.domain import Scenario
from gridsense.service import evaluate


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, default=Path(__file__).parent / "results")
    args = parser.parse_args()
    directory = args.output_dir
    if directory.exists() and any(directory.iterdir()):
        parser.error("Output directory is not empty; choose a new directory")
    directory.mkdir(parents=True, exist_ok=True)
    rows = []
    manifest = None
    case_number = 0
    for west in (0.6, 0.8, 1.0, 1.3, 1.6, 1.9):
        for east in (0.7, 1.0, 1.3, 1.6):
            for regime in ("current", "wide_assumed_range", "narrow_assumed_range"):
                reported = (
                    west
                    if regime == "current"
                    else max(0.5, west / 1.4 if regime == "wide_assumed_range" else west / 1.9)
                )
                uncertainty = (
                    0 if regime == "current" else 50 if regime == "wide_assumed_range" else 40
                )
                scenario = Scenario(
                    title=f"Benchmark {case_number:03d}",
                    load_b=west,
                    load_c=east,
                    reported_b=reported,
                    uncertainty_pct=uncertainty,
                    telemetry_age_s=0 if regime == "current" else 120,
                )
                incident = evaluate(scenario, "2026-01-01T12:00:00+00:00")
                manifest = incident["manifest"]
                for policy, outcome in incident["outcomes"].items():
                    result = outcome["result"]
                    rows.append(
                        {
                            "case": case_number,
                            "regime": regime,
                            "policy": policy,
                            "actual_west_factor": west,
                            "reported_west_factor": reported,
                            "actual_east_factor": east,
                            "uncertainty_pct": uncertainty,
                            "truth_inside_assumed_range": reported * (1 - uncertainty / 100) - 1e-9
                            <= west
                            <= reported * (1 + uncertainty / 100) + 1e-9,
                            "action": outcome["action"]["id"],
                            "feasible": result["feasible"],
                            "restored_kw": result["restored_kw"],
                            "critical_served_kw": result["critical_served_kw"],
                            "unserved_kw": result["unserved_kw"],
                            "feasible_restored_kw": result["restored_kw"]
                            if result["feasible"]
                            else 0,
                            "max_loading_pct": result["max_loading_pct"],
                            "min_voltage_pu": result["min_voltage_pu"],
                            "switch_operations": len(outcome["action"]["operations"]),
                            "violations": "; ".join(v["message"] for v in result["violations"]),
                        }
                    )
                case_number += 1
    summary = []
    for regime in ("all", "current", "wide_assumed_range", "narrow_assumed_range"):
        for policy in ("nominal", "guarded", "oracle"):
            selected = [
                r
                for r in rows
                if r["policy"] == policy and (regime == "all" or r["regime"] == regime)
            ]
            summary.append(
                {
                    "regime": regime,
                    "policy": policy,
                    "cases": len(selected),
                    "violations": sum(not r["feasible"] for r in selected),
                    "mean_restored_kw": statistics.mean(r["restored_kw"] for r in selected),
                    "mean_feasible_restored_kw": statistics.mean(
                        r["feasible_restored_kw"] for r in selected
                    ),
                    "mean_unserved_kw": statistics.mean(r["unserved_kw"] for r in selected),
                }
            )
    methodology = {
        "cases": case_number,
        "controller_outcomes": len(rows),
        "manifest": manifest,
        "design": "Cartesian grid: 6 west loads × 4 east loads × 3 telemetry assumptions. All outcomes retained.",
        "fairness": "Nominal and guarded receive identical observations per case. Oracle alone receives actual demand.",
        "limits": "No train/test claim; deterministic engineering scenarios on one custom feeder. Assumed uncertainty is not calibrated. Not evidence of utility performance or research novelty.",
        "summary": summary,
    }
    (directory / "benchmark.json").write_text(
        json.dumps({**methodology, "rows": rows}, indent=2, allow_nan=False) + "\n"
    )
    table = pa.Table.from_pylist(rows).replace_schema_metadata(
        {b"gridsense_manifest": json.dumps(methodology).encode()}
    )
    pq.write_table(table, directory / "benchmark.parquet")
    lines = [
        "# Reproducible benchmark",
        "",
        methodology["design"],
        "",
        methodology["fairness"],
        "",
        methodology["limits"],
        "",
        "| Regime | Controller | Cases | Violations | Mean restored kW | Mean feasible restored kW |",
        "| --- | --- | ---: | ---: | ---: | ---: |",
    ]
    for r in summary:
        lines.append(
            f"| {r['regime']} | {r['policy']} | {r['cases']} | {r['violations']} | {r['mean_restored_kw']:.1f} | {r['mean_feasible_restored_kw']:.1f} |"
        )
    lines += [
        "",
        "Feasible restored kW gives zero credit to an outcome violating a modeled limit. It is reported alongside raw restored demand, not as a replacement for the violation count.",
        "",
        "These are finite, correlated cases on one feeder. No statistical generalization or continuous uncertainty guarantee is inferred.",
        "",
        f"Implementation SHA-256: `{manifest['implementation_sha256']}`",
        "",
        "Reproduce: `python experiments/run_benchmark.py` from the project root in the installed environment.",
        "",
    ]
    (directory / "SUMMARY.md").write_text("\n".join(lines))
    print(f"Saved {case_number} cases / {len(rows)} controller outcomes to {directory.resolve()}")
    print("\n".join(lines[8:12]))


if __name__ == "__main__":
    main()
