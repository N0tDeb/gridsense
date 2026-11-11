"""Frozen episode comparison, permutation reference and finite uncertainty checks."""

import argparse
import gzip
import hashlib
import json
import platform
import statistics
from datetime import datetime, timezone
from pathlib import Path
from time import perf_counter

from gridsense.electrical import ElectricalEngine
from gridsense.episodes import (
    EpisodeConfig,
    advance_episode,
    canonical_hash,
    episode_hash,
    start_episode,
)
from gridsense.restoration import PlanningTiming, PlanningView, Predictor, dense_samples
from gridsense.restoration_reference import enumerate_plans
from gridsense.switching import SwitchOperation, change_position

ROOT = Path(__file__).resolve().parents[1]
PROTOCOL = ROOT / "experiments/protocols/sessions.json"


def file_hash(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def compact_outcome(state, frames):
    metrics = state.metrics.model_dump(mode="json")
    return {
        **metrics,
        "first_recovery_delay_s": state.metrics.first_recovery_delay_s,
        "final_unserved_kw": state.last_electrical["unserved_kw"]
        if state.last_electrical
        else None,
        "final_supply_status": state.control.supply_status,
        "commands": len(state.control.commands),
        "decisions": state.control.decision_count,
        "planning_native_evaluations": state.control.native_evaluations,
        "physical_native_evaluations": len(frames),
        "unconfirmed_commands": sum(
            c.status in {"pending", "unknown"} for c in state.control.commands.values()
        ),
        "budget_exhausted_decisions": len(
            {
                f["control"]["plan_id"]
                for f in frames
                if f["control"]["last_plan"] and f["control"]["last_plan"]["budget_exhausted"]
            }
        ),
    }


def dense_check(view, operations, engine, levels):
    rows, native = [], 0
    for index, demand in enumerate(dense_samples(view, levels)):
        predictor = Predictor(view, "nominal", max(1, len(operations)), engine, samples=[demand])
        state, steps = view.state, []
        for operation in operations:
            state = change_position(
                state, SwitchOperation.model_validate(operation), engine.network
            )
            result = predictor.evaluate(state)
            steps.append(result)
            if not result["feasible"]:
                break
        if not operations:
            steps.append(predictor.evaluate(state))
        feasible = all(s["feasible"] for s in steps)
        rows.append(
            {
                "sample": index,
                "demand_kw": demand,
                "feasible": feasible,
                "steps_checked": len(steps),
                "violations": [v for s in steps for v in s["violations"]],
                "worst_loading_pct": max(s["worst_loading_pct"] or 0 for s in steps),
                "minimum_voltage_pu": min(
                    (
                        s["nominal"]["min_voltage_pu"]
                        for s in steps
                        if s["nominal"]["min_voltage_pu"] is not None
                    ),
                    default=None,
                ),
            }
        )
        native += predictor.solves
    return {
        "samples": len(rows),
        "violating_samples": sum(not r["feasible"] for r in rows),
        "native_evaluations": native,
        "rows": rows,
    }


def verify_report(directory):
    report = json.loads((directory / "results.json").read_text(encoding="utf-8"))
    protocol = json.loads(PROTOCOL.read_text(encoding="utf-8"))
    manifest = report["manifest"]
    required = {
        "episode_sha256": episode_hash(),
        "protocol_sha256": file_hash(PROTOCOL),
        "runner_sha256": file_hash(Path(__file__)),
        "enumerator_sha256": file_hash(ROOT / "backend/gridsense/restoration_reference.py"),
        "traces_sha256": file_hash(directory / "episodes.jsonl.gz"),
    }
    if (
        any(manifest[key] != value for key, value in required.items())
        or report["protocol"] != protocol
    ):
        raise ValueError("Session study source, protocol or trace fingerprint mismatch")
    expected = {
        (case["id"], policy) for case in protocol["cases"] for policy in protocol["policies"]
    }
    if {(r["case"], r["policy"]) for r in report["rows"]} != expected or len(report["rows"]) != len(
        expected
    ):
        raise ValueError("Session study denominator mismatch")
    traces = []
    with gzip.open(directory / "episodes.jsonl.gz", "rt", encoding="utf-8") as handle:
        for line in handle:
            traces.append(json.loads(line))
    if len(traces) != len(expected):
        raise ValueError("Missing episode trace")
    for trace, row in zip(traces, report["rows"], strict=True):
        if (trace["case"], trace["policy"]) != (row["case"], row["policy"]) or canonical_hash(
            trace
        ) != row["trace_sha256"]:
            raise ValueError("Episode trace mismatch")
        frames, summary = trace["frames"], row["outcome"]
        if [f["at_s"] for f in frames] != list(range(protocol["horizon_s"] + 1)):
            raise ValueError("Episode did not finish the fixed horizon")
        # Recompute accumulated service directly from stored physical results,
        # without using the episode's metrics accumulator.
        for key, source in (
            ("served_kwh", "served_kw"),
            ("critical_served_kwh", "critical_served_kw"),
            ("unserved_kwh", "unserved_kw"),
        ):
            measured = sum(f["electrical"][source] / 3600 for f in frames[:-1] if f["electrical"])
            if abs(summary[key] - measured) > 1e-7:
                raise ValueError("Integrated physical metric mismatch")
        if summary["unknown_seconds"] != sum(f["electrical"] is None for f in frames[:-1]):
            raise ValueError("Unknown interval accounting mismatch")
        if summary["violation_ticks"] != sum(
            bool(f["electrical"] and not f["electrical"]["feasible"]) for f in frames
        ):
            raise ValueError("Violation count mismatch")
        if any(
            f["control"]["native_evaluations"] - p["control"]["native_evaluations"]
            > protocol["control"]["evaluation_budget"]
            for p, f in zip(frames, frames[1:])
        ):
            raise ValueError("Per-tick native evaluation budget exceeded")
    if not all(row["matched"] for row in report["references"]):
        raise ValueError("Production plan differs from the independent enumerator")
    if len(report["references"]) != len(protocol["reference_cases"]) * 2 + 2:
        raise ValueError("Missing restoration or normal-recovery reference")
    if len(report["dense_checks"]) != len(protocol["dense_cases"]) * 2:
        raise ValueError("Missing finite uncertainty comparison")
    for checked in report["dense_checks"]:
        if (
            checked["samples"] != 729
            or len(checked["rows"]) != 729
            or checked["violating_samples"] != sum(not r["feasible"] for r in checked["rows"])
        ):
            raise ValueError("Finite uncertainty denominator mismatch")
    return {
        "episodes": len(traces),
        "reference_matches": len(report["references"]),
        "dense_plans": len(report["dense_checks"]),
        "source_and_accounting_verified": True,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, default=ROOT / "experiments/session_results")
    parser.add_argument("--verify-report", action="store_true")
    args = parser.parse_args()
    output = args.output_dir.resolve()
    if args.verify_report:
        print(json.dumps(verify_report(output), indent=2))
        return
    if output.exists() and any(output.iterdir()):
        raise ValueError("Use a new empty output directory; preserve previous evidence")
    output.mkdir(parents=True, exist_ok=True)
    protocol = json.loads(PROTOCOL.read_text(encoding="utf-8"))
    engine = ElectricalEngine()
    started, rows, references, dense = perf_counter(), [], [], []
    with gzip.open(output / "episodes.jsonl.gz", "wt", encoding="utf-8") as traces:
        for case in protocol["cases"]:
            for policy in protocol["policies"]:
                config = EpisodeConfig.model_validate(
                    {
                        "title": case["id"],
                        "horizon_s": protocol["horizon_s"],
                        "initial_factors": case.get("initial_factors", {"a": 1, "b": 1, "c": 1}),
                        "control": {**protocol["control"], "policy": policy},
                        "measurements": protocol["measurements"],
                        "events": case["events"],
                    }
                )
                timer = perf_counter()
                state, frame = start_episode(config, engine)
                frames = [frame]
                for _ in range(config.horizon_s):
                    state, frame = advance_episode(state, engine)
                    frames.append(frame)
                elapsed = perf_counter() - timer
                trace = {
                    "case": case["id"],
                    "policy": policy,
                    "definition": config.model_dump(mode="json"),
                    "manifest": state.manifest,
                    "frames": frames,
                }
                traces.write(json.dumps(trace, separators=(",", ":"), allow_nan=False) + "\n")
                traces.flush()
                outcome = compact_outcome(state, frames)
                rows.append(
                    {
                        "case": case["id"],
                        "policy": policy,
                        "outcome": outcome,
                        "wall_seconds": elapsed,
                        "trace_sha256": canonical_hash(trace),
                    }
                )
                print(
                    json.dumps(
                        {
                            "case": case["id"],
                            "policy": policy,
                            "seconds": elapsed,
                            "unserved_kwh": outcome["unserved_kwh"],
                            "violation_ticks": outcome["violation_ticks"],
                        }
                    ),
                    flush=True,
                )
                if policy == "off":
                    continue
                plans = [
                    f["control"]["last_plan"]
                    for f in frames
                    if any(e["kind"] == "plan_evaluated" for e in f["control_events"])
                ]
                if not plans:
                    raise ValueError(
                        "Study expected at least one decision; retain and inspect the incomplete run"
                    )
                to_check = []
                if case["id"] in protocol["reference_cases"]:
                    to_check.append(plans[0])
                if case["id"] == "feeder-repair":
                    to_check.append(next(p for p in plans if p["goal"] == "normal"))
                for proposal in to_check:
                    view = PlanningView.model_validate(proposal["input"])
                    timer = perf_counter()
                    reference = enumerate_plans(
                        view,
                        policy,
                        engine=engine,
                        max_operations=protocol["control"]["max_operations"],
                        goal=proposal["goal"],
                        timing=PlanningTiming.model_validate(proposal["timing"]),
                    )
                    operations = (
                        proposal["selected"]["operations"] if proposal["feasible_choice"] else []
                    )
                    matched = (
                        not proposal["budget_exhausted"]
                        and proposal["feasible_choice"] == reference["feasible_choice"]
                        and operations == reference["operations"]
                    )
                    references.append(
                        {
                            "case": case["id"],
                            "policy": policy,
                            "goal": proposal["goal"],
                            "at_s": view.at_s,
                            "matched": matched,
                            "wall_seconds": perf_counter() - timer,
                            "production_native_evaluations": proposal["native_evaluations"],
                            "production_operations": operations,
                            "reference": reference,
                        }
                    )
                if case["id"] in protocol["dense_cases"]:
                    proposal = plans[0]
                    if not proposal["feasible_choice"]:
                        raise ValueError(
                            "No selected feasible plan for the frozen dense comparison"
                        )
                    view = PlanningView.model_validate(proposal["input"])
                    timer = perf_counter()
                    checked = dense_check(
                        view, proposal["selected"]["operations"], engine, protocol["dense_levels"]
                    )
                    dense.append(
                        {
                            "case": case["id"],
                            "policy": policy,
                            "at_s": view.at_s,
                            "operations": proposal["selected"]["operations"],
                            **checked,
                            "wall_seconds": perf_counter() - timer,
                        }
                    )
    report = {
        "manifest": {
            "recorded_at": datetime.now(timezone.utc).isoformat(),
            "episode_sha256": episode_hash(),
            "protocol_sha256": file_hash(PROTOCOL),
            "runner_sha256": file_hash(Path(__file__)),
            "enumerator_sha256": file_hash(ROOT / "backend/gridsense/restoration_reference.py"),
            "traces_sha256": file_hash(output / "episodes.jsonl.gz"),
            "solver_version": engine.version,
            "python": platform.python_version(),
            "platform": platform.system(),
            "interpretation": "Finite inspected engineering cases; shared electrical model; times are single-run measurements on this host; no field or continuous-robustness claim",
        },
        "protocol": protocol,
        "rows": rows,
        "references": references,
        "dense_checks": dense,
        "costs": {
            "total_wall_seconds": perf_counter() - started,
            "episode_native_evaluations": sum(
                r["outcome"]["planning_native_evaluations"]
                + r["outcome"]["physical_native_evaluations"]
                for r in rows
            ),
            "reference_native_evaluations": sum(
                r["reference"]["native_evaluations"] for r in references
            ),
            "dense_native_evaluations": sum(r["native_evaluations"] for r in dense),
        },
        "summary": {
            policy: {
                "episodes": len(protocol["cases"]),
                "unserved_kwh": sum(
                    r["outcome"]["unserved_kwh"] for r in rows if r["policy"] == policy
                ),
                "violation_ticks": sum(
                    r["outcome"]["violation_ticks"] for r in rows if r["policy"] == policy
                ),
                "median_episode_wall_seconds": statistics.median(
                    r["wall_seconds"] for r in rows if r["policy"] == policy
                ),
            }
            for policy in protocol["policies"]
        },
    }
    (output / "results.json").write_text(
        json.dumps(report, indent=2, allow_nan=False) + "\n", encoding="utf-8"
    )
    print(json.dumps(verify_report(output), indent=2))


if __name__ == "__main__":
    main()
