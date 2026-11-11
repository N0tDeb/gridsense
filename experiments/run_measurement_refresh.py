"""Three inspected evidence-refresh cases, including a near-limit negative case."""

import argparse
import gzip
import hashlib
import json
from pathlib import Path

from gridsense.episodes import canonical_hash, episode_hash
from gridsense.session_store import CreateSession, SessionMutation, SessionStore, replay_episode
from gridsense.service import utc_now
from run_session_challenge import physical_accounting

ROOT = Path(__file__).resolve().parents[1]
PROTOCOL = ROOT / "experiments/protocols/measurement_refresh.json"


def write_json(path, value):
    path.write_text(json.dumps(value, indent=2, allow_nan=False) + "\n", encoding="utf-8")


def load_protocol():
    protocol = json.loads(PROTOCOL.read_text(encoding="utf-8"))
    if protocol["episode_sha256"] != episode_hash():
        raise ValueError("Source differs from this study's pinned implementation")
    return protocol


def outcome(export):
    frames = export["frames"]
    return {
        **physical_accounting(frames),
        "commands": [
            {key: command[key] for key in ("id", "operation", "issued_at_s", "status")}
            for command in frames[-1]["control"]["commands"].values()
        ],
        "cancelled_sequences": sum(
            event["kind"] == "sequence_revalidation" and not event["feasible"]
            for frame in frames
            for event in frame["control_events"]
        ),
        "all_physical_frames_feasible": all(
            frame["electrical"] is not None and frame["electrical"]["feasible"] for frame in frames
        ),
    }


def verify(directory):
    protocol = load_protocol()
    report = json.loads((directory / "results.json").read_text(encoding="utf-8"))
    if (
        report["protocol"] != protocol
        or report["runner_sha256"] != hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    ):
        raise ValueError("Study protocol or runner differs")
    if len(report["rows"]) != len(protocol["cases"]):
        raise ValueError("Incomplete study")
    for case, row in zip(protocol["cases"], report["rows"], strict=True):
        with gzip.open(directory / (case["id"] + ".json.gz"), "rt", encoding="utf-8") as handle:
            export = json.load(handle)
        if export["manifest"]["episode_sha256"] != protocol["episode_sha256"] or export[
            "content_sha256"
        ] != canonical_hash(
            {key: value for key, value in export.items() if key != "content_sha256"}
        ):
            raise ValueError("Recorded source identity or export checksum differs")
        if (
            export["definition"] != case["config"]
            or row["case"] != case["id"]
            or canonical_hash(export) != row["trace_sha256"]
        ):
            raise ValueError("Case or trace differs")
        if outcome(export) != row["outcome"] or not row["replay"]["matched"]:
            raise ValueError("Physical accounting or recorded replay failed")
        if [frame["at_s"] for frame in export["frames"]] != list(
            range(case["config"]["horizon_s"] + 1)
        ):
            raise ValueError("Incomplete fixed horizon")
    return {"cases": len(report["rows"]), "source_and_accounting_verified": True}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, default=ROOT / "experiments/refresh_results")
    parser.add_argument("--verify-report", action="store_true")
    args = parser.parse_args()
    if args.verify_report:
        print(json.dumps(verify(args.output_dir), indent=2))
        return
    protocol = load_protocol()
    if args.output_dir.exists() and any(args.output_dir.iterdir()):
        parser.error("Use a new empty output directory")
    args.output_dir.mkdir(parents=True, exist_ok=True)
    # Runtime SQLite data stays outside the experiment deliverable directory.
    import tempfile

    rows = []
    started_at = utc_now()
    with tempfile.TemporaryDirectory(prefix="gridsense-refresh-") as scratch:
        store = SessionStore(Path(scratch) / "sessions.sqlite3")
        for case in protocol["cases"]:
            receipt = store.create(CreateSession(request_id=case["id"], config=case["config"]))
            for tick in range(case["config"]["horizon_s"]):
                receipt = store.mutate(
                    receipt["id"],
                    SessionMutation(
                        request_id=f"step-{tick}",
                        expected_revision=receipt["revision"],
                        operation="step",
                    ),
                )
            export = store.export(receipt["id"])
            replay = replay_episode(export)
            if not replay["matched"]:
                raise ValueError("Fresh episode replay differs")
            with gzip.open(
                args.output_dir / (case["id"] + ".json.gz"), "wt", encoding="utf-8"
            ) as handle:
                json.dump(export, handle, separators=(",", ":"), allow_nan=False)
            row = {
                "case": case["id"],
                "outcome": outcome(export),
                "trace_sha256": canonical_hash(export),
                "replay": replay,
            }
            rows.append(row)
            print(
                json.dumps(
                    {
                        "case": case["id"],
                        "unserved_kwh": row["outcome"]["unserved_kwh"],
                        "replay_matched": replay["matched"],
                    }
                ),
                flush=True,
            )
    write_json(
        args.output_dir / "results.json",
        {
            "started_at": started_at,
            "completed_at": utc_now(),
            "protocol": protocol,
            "runner_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
            "rows": rows,
        },
    )
    print(json.dumps(verify(args.output_dir)), flush=True)


if __name__ == "__main__":
    main()
