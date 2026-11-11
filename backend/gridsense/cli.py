"""Headless experiments use the same service functions as the web application."""

import argparse
import json
from pathlib import Path
from .domain import Scenario, SweepInput
from .service import create_incident, replay, sweep
from .storage import IncidentStore
from .failure_search import SearchInput, replay_search, run_search
from .cases import PortableCase, RegressionInput, case_from_incident
from .regression import run_regression, rerun_regression, replay_regression
from .temporal import TemporalInput, run_temporal, replay_temporal
from .published_reference import validate_published_reference as validate_reference
from .electrical import ElectricalEngine
from .episodes import EpisodeConfig
from .session_store import CreateSession, SessionMutation, SessionStore, replay_episode


def read_json_object(path: Path) -> dict:
    """Read a UTF-8 JSON object and reject arrays or scalar values."""
    value = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(value, dict):
        raise ValueError(f"{path.name}: expected a JSON object")
    return value


def main():
    parser = argparse.ArgumentParser(
        description="GridSense grid-restoration simulator and controller tests"
    )
    parser.add_argument(
        "command",
        choices=[
            "serve",
            "demo",
            "sweep",
            "replay",
            "search",
            "reproduce",
            "regress",
            "temporal",
            "validate-feeder",
            "verify-run",
            "episode",
            "replay-episode",
        ],
    )
    parser.add_argument("--data-dir", default="var")
    parser.add_argument("--port", default=8000, type=int)
    parser.add_argument("--incident", help="Stored incident ID for replay")
    parser.add_argument("--output", type=Path, help="Write JSON result to this file")
    parser.add_argument("--file", type=Path, help="UTF-8 JSON portable case or exported run")
    parser.add_argument(
        "--config", type=Path, help="UTF-8 JSON settings for search, temporal or episode"
    )
    parser.add_argument("--seed", type=int, default=42, help="Failure search seed")
    parser.add_argument(
        "--budget", type=int, default=24, help="Incident evaluations per search method"
    )
    parser.add_argument("--policy", choices=["nominal", "guarded"], default="nominal")
    parser.add_argument(
        "--candidate", choices=["nominal-v1", "guarded-v1", "hold-v1"], default="guarded-v1"
    )
    args = parser.parse_args()
    if args.command == "serve":
        import os
        import uvicorn

        os.environ["GRIDSENSE_DATA_DIR"] = args.data_dir
        uvicorn.run("gridsense.api:app", host="127.0.0.1", port=args.port)
        return
    if args.command in {"episode", "replay-episode"}:
        try:
            if args.command == "replay-episode":
                if not args.file:
                    parser.error("replay-episode requires --file")
                result = replay_episode(read_json_object(args.file))
            else:
                from uuid import uuid4

                config = EpisodeConfig.model_validate(
                    read_json_object(args.config) if args.config else {}
                )
                store = SessionStore(
                    Path(args.data_dir) / "gridsense.sqlite3", engine=ElectricalEngine()
                )
                receipt = store.create(CreateSession(request_id=str(uuid4()), config=config))
                while receipt["at_s"] < config.horizon_s and not receipt["pause_reason"]:
                    receipt = store.mutate(
                        receipt["id"],
                        SessionMutation(
                            request_id="step-" + str(receipt["revision"]),
                            expected_revision=receipt["revision"],
                            operation="step",
                        ),
                    )
                result = store.export(receipt["id"])
        except (ValueError, KeyError, TypeError, OSError) as exc:
            parser.error(str(exc))
    elif args.command in {"regress", "temporal", "validate-feeder", "verify-run"}:
        try:
            data = read_json_object(args.file) if args.file else None
            if args.command == "validate-feeder":
                result = validate_reference()
            elif args.command == "verify-run":
                if not data or data.get("kind") not in {"regression", "temporal"}:
                    parser.error(
                        "verify-run requires --file containing a regression or temporal export"
                    )
                result = (replay_regression if data["kind"] == "regression" else replay_temporal)(
                    data
                )
            elif args.command == "temporal":
                config = (
                    read_json_object(args.config)
                    if args.config
                    else {"seed": args.seed, "budget": args.budget}
                )
                result = run_temporal(TemporalInput.model_validate(config))
            elif data and data.get("kind") == "regression":
                result = rerun_regression(data, args.candidate)
            else:
                if data and "reduced_incident" in data:
                    if data["reduced_incident"] is None:
                        raise ValueError("The search contains no reduced failure")
                    case = case_from_incident(data["reduced_incident"])
                elif data and "manifest" in data and "scenario" in data:
                    case = case_from_incident(data)
                else:
                    case = PortableCase.model_validate(data or {})
                result = run_regression(RegressionInput(case=case, candidate=args.candidate))
            if args.command in {"regress", "temporal"}:
                IncidentStore(Path(args.data_dir) / "gridsense.sqlite3").save_verification(result)
        except (ValueError, KeyError, TypeError, OSError) as exc:
            parser.error(str(exc))
    elif args.command == "reproduce":
        if not args.file:
            parser.error("reproduce requires --file")
        try:
            result = replay_search(read_json_object(args.file))
        except (ValueError, KeyError, TypeError, OSError) as exc:
            parser.error(str(exc))
    else:
        store = IncidentStore(Path(args.data_dir) / "gridsense.sqlite3")
    if args.command == "demo":
        result = create_incident(Scenario(), store)
    elif args.command == "sweep":
        result = sweep(SweepInput(), store)
    elif args.command == "search":
        try:
            config = (
                read_json_object(args.config)
                if args.config
                else {"seed": args.seed, "budget": args.budget, "policy": args.policy}
            )
            result = run_search(SearchInput.model_validate(config))
        except (ValueError, OSError) as exc:
            parser.error(str(exc))
        store.save_search(result)
    elif args.command == "replay":
        if not args.incident:
            parser.error("replay requires --incident")
        try:
            result = replay(store.get(args.incident))
        except (ValueError, KeyError, TypeError, OSError) as exc:
            parser.error(str(exc))
    serialized = json.dumps(result, indent=2, allow_nan=False)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(serialized + "\n", encoding="utf-8")
        print(args.output.resolve())
    else:
        print(serialized)
    if (
        (
            args.command in {"replay", "reproduce", "verify-run", "replay-episode"}
            and not result["matched"]
        )
        or (args.command == "regress" and not result["accepted"])
        or (args.command == "validate-feeder" and not result["passed"])
        or (args.command == "episode" and result["final"]["checkpoint"]["last_error"] is not None)
    ):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
