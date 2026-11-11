"""Frozen internal boundary cases; complete traces and independently counted outcomes.

Freeze before execution. A freeze is an engineering record, not an externally
registered protocol or evidence that these inspected cases are an unseen set.
"""

import argparse
import csv
import gzip
import hashlib
import json
import math
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
from run_session_benchmark import compact_outcome

ROOT = Path(__file__).resolve().parents[1]
PROTOCOL = ROOT / "experiments/protocols/session_challenge.json"
FREEZE = PROTOCOL.with_suffix(".freeze.json")


def file_hash(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def fingerprints():
    return {
        "episode_sha256": episode_hash(),
        "protocol_sha256": file_hash(PROTOCOL),
        "runner_sha256": file_hash(Path(__file__)),
        "outcome_helper_sha256": file_hash(ROOT / "experiments/run_session_benchmark.py"),
    }


def definition(protocol, case, policy):
    return EpisodeConfig.model_validate(
        {
            "title": case["id"],
            "horizon_s": protocol["horizon_s"],
            "initial_factors": case.get("initial_factors", {"a": 1, "b": 1, "c": 1}),
            "control": {**protocol["control"], **case.get("control", {}), "policy": policy},
            "measurements": {**protocol["measurements"], **case.get("measurements", {})},
            "events": case["events"],
        }
    )


def checked_protocol():
    protocol = json.loads(PROTOCOL.read_text(encoding="utf-8"))
    ids = [case["id"] for case in protocol["cases"]]
    if len(set(ids)) != len(ids) or protocol["policies"] != ["off", "nominal", "guarded"]:
        raise ValueError("Duplicate cases or unexpected policy comparison")
    for case in protocol["cases"]:
        for policy in protocol["policies"]:
            definition(protocol, case, policy)
    return protocol


def physical_accounting(frames):
    """Count stored native frames/events without calling the metrics accumulator."""
    intervals = [f["electrical"] for f in frames[:-1] if f["electrical"] is not None]
    samples = [f["electrical"] for f in frames if f["electrical"] is not None]
    result = {
        "known_seconds": len(intervals),
        "unknown_seconds": len(frames) - 1 - len(intervals),
        "violation_ticks": sum(not e["feasible"] for e in samples),
        "violation_seconds": sum(not e["feasible"] for e in intervals),
        "unknown_samples": len(frames) - len(samples),
    }
    for metric, source, feasible_only in (
        ("requested_kwh", "requested_kw", False),
        ("served_kwh", "served_kw", False),
        ("critical_served_kwh", "critical_served_kw", False),
        ("unserved_kwh", "unserved_kw", False),
        ("feasible_served_kwh", "served_kw", True),
        ("feasible_critical_served_kwh", "critical_served_kw", True),
    ):
        result[metric] = sum(
            e[source] / 3600 for e in intervals if not feasible_only or e["feasible"]
        )
    interruption, recovery = None, None
    for frame in frames:
        e = frame["electrical"]
        if e is None:
            continue
        interrupted = e["unserved_kw"] > 0.1 or not e["feasible"]
        if interrupted and interruption is None:
            interruption = frame["at_s"]
        if not interrupted and interruption is not None and recovery is None:
            recovery = frame["at_s"]
    result.update(
        first_interruption_s=interruption,
        first_full_recovery_s=recovery,
        first_recovery_delay_s=None if recovery is None else recovery - interruption,
        actuation_attempts=sum(len(f["actuation_events"]) for f in frames),
        position_changes=sum(e["changed"] for f in frames for e in f["actuation_events"]),
        final_unserved_kw=frames[-1]["electrical"]["unserved_kw"]
        if frames[-1]["electrical"] is not None
        else None,
        physical_native_evaluations=len(frames),
    )
    return result


def assert_values(actual, expected, label):
    for key, value in expected.items():
        other = actual[key]
        if isinstance(value, float):
            equal = (
                isinstance(other, (float, int))
                and math.isfinite(other)
                and math.isclose(other, value, rel_tol=1e-10, abs_tol=1e-7)
            )
        else:
            equal = other == value
        if not equal:
            raise ValueError(f"{label}: {key} differs ({other!r} versus {value!r})")


def policy_summary(rows, policies):
    summary = {}
    for policy in policies:
        chosen = [r for r in rows if r["policy"] == policy]
        summary[policy] = {
            "episodes": len(chosen),
            **{
                key: sum(r["outcome"][key] for r in chosen)
                for key in (
                    "known_seconds",
                    "unknown_seconds",
                    "unserved_kwh",
                    "feasible_critical_served_kwh",
                    "violation_ticks",
                    "violation_seconds",
                    "commands",
                    "position_changes",
                    "planning_native_evaluations",
                    "physical_native_evaluations",
                    "unconfirmed_commands",
                    "budget_exhausted_decisions",
                )
            },
            "median_wall_seconds": statistics.median(r["wall_seconds"] for r in chosen),
            "total_wall_seconds": sum(r["wall_seconds"] for r in chosen),
        }
    return summary


def table_rows(rows):
    return [
        {
            "case": r["case"],
            "pair": r["pair"],
            "policy": r["policy"],
            **r["outcome"],
            "wall_seconds": r["wall_seconds"],
        }
        for r in rows
    ]


def verify_report(directory):
    report = json.loads((directory / "results.json").read_text(encoding="utf-8"))
    protocol = checked_protocol()
    freeze = json.loads(FREEZE.read_text(encoding="utf-8"))
    if freeze["fingerprints"] != fingerprints() or report["freeze"] != freeze:
        raise ValueError("Frozen source or protocol changed")
    if report["protocol"] != protocol or report["traces_sha256"] != file_hash(
        directory / "episodes.jsonl.gz"
    ):
        raise ValueError("Protocol or trace fingerprint mismatch")
    if datetime.fromisoformat(report["started_at"]) < datetime.fromisoformat(freeze["frozen_at"]):
        raise ValueError("Execution predates freeze")
    expected = [(c, p) for c in protocol["cases"] for p in protocol["policies"]]
    if len(report["rows"]) != len(expected):
        raise ValueError("Incomplete challenge denominator")
    with gzip.open(directory / "episodes.jsonl.gz", "rt", encoding="utf-8") as handle:
        traces = [json.loads(line) for line in handle]
    if len(traces) != len(expected):
        raise ValueError("Incomplete trace denominator")
    for (case, policy), row, trace in zip(expected, report["rows"], traces, strict=True):
        config = definition(protocol, case, policy)
        if (row["case"], row["policy"]) != (case["id"], policy) or (
            trace["case"],
            trace["policy"],
        ) != (case["id"], policy):
            raise ValueError("Case or policy order changed")
        if (
            trace["definition"] != config.model_dump(mode="json")
            or canonical_hash(trace) != row["trace_sha256"]
        ):
            raise ValueError("Definition or trace mismatch")
        if (
            trace["manifest"]["episode_sha256"] != freeze["fingerprints"]["episode_sha256"]
            or trace["manifest"]["solver_version"] != report["environment"]["native_solver"]
        ):
            raise ValueError("Source or solver identity mismatch")
        frames = trace["frames"]
        if [f["at_s"] for f in frames] != list(range(protocol["horizon_s"] + 1)):
            raise ValueError("Incomplete fixed horizon")
        accounted = physical_accounting(frames)
        assert_values(row["outcome"], accounted, "Physical accounting")
        assert_values(row["outcome"], frames[-1]["metrics"], "Episode metrics")
        control = frames[-1]["control"]
        expected_control = {
            "commands": len(control["commands"]),
            "decisions": control["decision_count"],
            "planning_native_evaluations": control["native_evaluations"],
            "unconfirmed_commands": sum(
                c["status"] in {"pending", "unknown"} for c in control["commands"].values()
            ),
            "final_supply_status": control["supply_status"],
            "budget_exhausted_decisions": len(
                {
                    f["control"]["plan_id"]
                    for f in frames
                    if f["control"]["last_plan"] and f["control"]["last_plan"]["budget_exhausted"]
                }
            ),
        }
        assert_values(row["outcome"], expected_control, "Controller accounting")
        if (
            len(control["commands"]) > config.control.max_commands
            or control["decision_count"] > config.control.max_decisions
        ):
            raise ValueError("Command or decision cap exceeded")
        previous = 0
        for frame in frames:
            current = frame["control"]["native_evaluations"]
            if not 0 <= current - previous <= config.control.evaluation_budget:
                raise ValueError("Per-decision native budget exceeded")
            previous = current
        if not math.isfinite(row["wall_seconds"]) or row["wall_seconds"] <= 0:
            raise ValueError("Missing measured episode cost")
    for policy, expected_summary in policy_summary(report["rows"], protocol["policies"]).items():
        assert_values(report["summary"][policy], expected_summary, "Summary")
    with (directory / "outcomes.csv").open(newline="", encoding="utf-8") as handle:
        table = list(csv.DictReader(handle))
    expected_table = [
        {k: "" if v is None else str(v) for k, v in row.items()}
        for row in table_rows(report["rows"])
    ]
    if table != expected_table:
        raise ValueError("Readable table differs from complete outcomes")
    return {
        "episodes": len(traces),
        "cases": len(protocol["cases"]),
        "horizon_s": protocol["horizon_s"],
        "source_and_accounting_verified": True,
    }


def run(output):
    protocol = checked_protocol()
    freeze = json.loads(FREEZE.read_text(encoding="utf-8"))
    if freeze["fingerprints"] != fingerprints():
        raise ValueError("Source/protocol differs from freeze; retain and label a new study")
    if output.exists() and any(output.iterdir()):
        raise ValueError("Use a new empty output directory; preserve prior evidence")
    output.mkdir(parents=True, exist_ok=True)
    engine, rows = ElectricalEngine(), []
    start, started_at = perf_counter(), datetime.now(timezone.utc).isoformat()
    with gzip.open(output / "episodes.jsonl.gz", "wt", encoding="utf-8") as handle:
        for case in protocol["cases"]:
            for policy in protocol["policies"]:
                config = definition(protocol, case, policy)
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
                handle.write(json.dumps(trace, separators=(",", ":"), allow_nan=False) + "\n")
                handle.flush()
                outcome = compact_outcome(state, frames)
                accounted = physical_accounting(frames)
                assert_values(
                    outcome,
                    {k: v for k, v in accounted.items() if k in outcome},
                    "Physical accounting",
                )
                outcome.update({k: v for k, v in accounted.items() if k not in outcome})
                row = {
                    "case": case["id"],
                    "pair": case["pair"],
                    "policy": policy,
                    "outcome": outcome,
                    "wall_seconds": elapsed,
                    "trace_sha256": canonical_hash(trace),
                }
                rows.append(row)
                print(json.dumps({k: v for k, v in row.items() if k != "trace_sha256"}), flush=True)
    report = {
        "schema_version": 1,
        "started_at": started_at,
        "completed_at": datetime.now(timezone.utc).isoformat(),
        "freeze": freeze,
        "protocol": protocol,
        "environment": {
            "python": platform.python_version(),
            "platform": platform.platform(),
            "native_solver": engine.version,
        },
        "traces_sha256": file_hash(output / "episodes.jsonl.gz"),
        "rows": rows,
        "summary": policy_summary(rows, protocol["policies"]),
        "total_wall_seconds": perf_counter() - start,
    }
    (output / "results.json").write_text(
        json.dumps(report, indent=2, allow_nan=False) + "\n", encoding="utf-8"
    )
    with (output / "outcomes.csv").open("w", newline="", encoding="utf-8") as handle:
        flattened = table_rows(rows)
        writer = csv.DictWriter(handle, fieldnames=list(flattened[0]))
        writer.writeheader()
        writer.writerows(flattened)
    print(json.dumps(verify_report(output)), flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, default=ROOT / "experiments/challenge_results")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--freeze", action="store_true")
    mode.add_argument("--verify-report", action="store_true")
    args = parser.parse_args()
    if args.freeze:
        checked_protocol()
        with FREEZE.open("x", encoding="utf-8") as handle:
            json.dump(
                {
                    "frozen_at": datetime.now(timezone.utc).isoformat(),
                    "scope": "Internal inspected synthetic challenge; no external registration or blind holdout",
                    "fingerprints": fingerprints(),
                },
                handle,
                indent=2,
            )
            handle.write("\n")
        print(FREEZE)
    elif args.verify_report:
        print(json.dumps(verify_report(args.output_dir.resolve()), indent=2))
    else:
        run(args.output_dir.resolve())


if __name__ == "__main__":
    main()
