"""Transactional session mutations and replayable logical actions."""

import json
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Literal
from uuid import uuid4

from pydantic import Field, TypeAdapter, model_validator

from .domain import Record
from .electrical import ElectricalEngine
from .episodes import (
    EpisodeConfig,
    EpisodeState,
    Event,
    advance_episode,
    assert_compatible,
    canonical_hash,
    controller_view,
    schedule,
    start_episode,
)
from .service import _differences, utc_now


class CreateSession(Record):
    request_id: str = Field(pattern=r"^[A-Za-z0-9_-]{1,80}$")
    config: EpisodeConfig = Field(default_factory=EpisodeConfig)


class SessionMutation(Record):
    request_id: str = Field(pattern=r"^[A-Za-z0-9_-]{1,80}$")
    expected_revision: int = Field(ge=0, strict=True)
    operation: Literal["step", "play", "pause", "rate", "schedule"]
    rate: Literal[1, 5, 10] | None = None
    events: tuple[Event, ...] = Field(default=(), max_length=128)

    @model_validator(mode="after")
    def required_arguments(self):
        if self.operation == "rate" and self.rate is None:
            raise ValueError("A rate change requires rate 1, 5 or 10")
        if self.rate is not None and self.operation not in {"rate", "play"}:
            raise ValueError("Only play or rate accepts a playback rate")
        if bool(self.events) != (self.operation == "schedule"):
            raise ValueError("Only schedule accepts a nonempty event list")
        return self


def apply_action(state, mode, rate, operation, payload, engine=None):
    frame, reason = None, None
    if operation in {"step", "auto_tick", "play", "schedule"}:
        engine = engine or ElectricalEngine()
        assert_compatible(state, engine)
    if operation in {"step", "auto_tick"}:
        required = "paused" if operation == "step" else "running"
        if mode != required:
            raise ValueError(f"{operation} requires a {required} session")
        state, frame = advance_episode(state, engine)
    elif operation == "schedule":
        state = schedule(state, TypeAdapter(tuple[Event, ...]).validate_python(payload["events"]))
    elif operation == "play":
        if state.now_s >= state.config.horizon_s or state.last_error:
            raise ValueError(
                "Cannot play a completed or invalid episode; inspect or single-step it"
            )
        mode, rate = "running", payload.get("rate") or rate
    elif operation in {"pause", "restart_pause", "worker_error"}:
        mode = "paused"
        reason = payload.get("reason")
    elif operation == "rate":
        rate = payload["rate"]
    else:
        raise ValueError("Unknown session operation")
    if rate not in (1, 5, 10):
        raise ValueError("Unsupported playback rate")
    if state.last_error or state.now_s >= state.config.horizon_s:
        mode = "paused"
        reason = state.last_error or "Episode horizon reached"
    return state, frame, mode, rate, reason


def encode(value):
    return json.dumps(value, allow_nan=False, separators=(",", ":"))


class SessionStore:
    def __init__(self, path, *, initialize=True, engine=None):
        self.path = Path(path).resolve()
        # A headless runner can reuse one context for its bounded episode.
        # HTTP jobs use a fresh worker process for each transaction.
        self.engine = engine
        if initialize:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with sqlite3.connect(self.path) as db:
                db.execute("PRAGMA journal_mode=WAL")
            with self.connect(write=True) as db:
                for sql in (
                    "CREATE TABLE IF NOT EXISTS live_sessions (id TEXT PRIMARY KEY, created_at TEXT NOT NULL, revision INTEGER NOT NULL, mode TEXT NOT NULL, rate INTEGER NOT NULL, reason TEXT, definition TEXT NOT NULL, checkpoint TEXT NOT NULL)",
                    "CREATE TABLE IF NOT EXISTS live_creations (request_id TEXT PRIMARY KEY, request_hash TEXT NOT NULL, receipt TEXT NOT NULL)",
                    "CREATE TABLE IF NOT EXISTS live_actions (session_id TEXT NOT NULL REFERENCES live_sessions(id), revision INTEGER NOT NULL, request_id TEXT NOT NULL, request_hash TEXT NOT NULL, operation TEXT NOT NULL, payload TEXT NOT NULL, receipt TEXT NOT NULL, PRIMARY KEY(session_id, revision), UNIQUE(session_id, request_id))",
                    "CREATE TABLE IF NOT EXISTS live_frames (session_id TEXT NOT NULL REFERENCES live_sessions(id), tick INTEGER NOT NULL, payload TEXT NOT NULL, PRIMARY KEY(session_id, tick))",
                ):
                    db.execute(sql)

    @contextmanager
    def connect(self, *, write=False):
        db = sqlite3.connect(self.path, timeout=10, isolation_level=None)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA foreign_keys=ON")
        try:
            db.execute("BEGIN IMMEDIATE" if write else "BEGIN")
            yield db
            db.commit()
        except BaseException:
            db.rollback()
            raise
        finally:
            db.close()

    @staticmethod
    def receipt(session_id, revision, state, mode, rate, reason):
        return {
            "id": session_id,
            "revision": revision,
            "at_s": state.now_s,
            "mode": mode,
            "rate": rate,
            "pause_reason": reason,
        }

    @staticmethod
    def find(db, session_id):
        row = db.execute("SELECT * FROM live_sessions WHERE id=?", (session_id,)).fetchone()
        if row is None:
            raise KeyError(session_id)
        return row

    def create(self, request):
        digest = canonical_hash(request.model_dump(mode="json"))
        with self.connect(write=True) as db:
            old = db.execute(
                "SELECT * FROM live_creations WHERE request_id=?", (request.request_id,)
            ).fetchone()
            if old:
                if old["request_hash"] != digest:
                    raise ValueError("Request ID was already used with another payload")
                return json.loads(old["receipt"])
            state, frame = start_episode(request.config, self.engine)
            session_id, at = str(uuid4()), utc_now()
            receipt = self.receipt(session_id, 0, state, "paused", 1, state.last_error)
            db.execute(
                "INSERT INTO live_sessions VALUES (?, ?, 0, 'paused', 1, ?, ?, ?)",
                (
                    session_id,
                    at,
                    state.last_error,
                    request.config.model_dump_json(),
                    state.model_dump_json(),
                ),
            )
            db.execute("INSERT INTO live_frames VALUES (?, 0, ?)", (session_id, encode(frame)))
            db.execute(
                "INSERT INTO live_creations VALUES (?, ?, ?)",
                (request.request_id, digest, encode(receipt)),
            )
            return receipt

    def mutate(self, session_id, request):
        payload = request.model_dump(
            mode="json", exclude={"request_id", "expected_revision", "operation"}
        )
        return self._mutate(
            session_id,
            "client:" + request.request_id,
            request.expected_revision,
            request.operation,
            payload,
            canonical_hash(request.model_dump(mode="json")),
        )

    def _mutate(self, session_id, request_id, expected_revision, operation, payload, digest):
        # Own the database mutation through native work. Cancellation cannot
        # release this transaction halfway through a tick/frame/action commit.
        with self.connect(write=True) as db:
            row = self.find(db, session_id)
            old = db.execute(
                "SELECT request_hash, receipt FROM live_actions WHERE session_id=? AND request_id=?",
                (session_id, request_id),
            ).fetchone()
            if old:
                if old["request_hash"] != digest:
                    raise ValueError("Request ID was already used with another payload")
                return json.loads(old["receipt"])
            if row["revision"] != expected_revision:
                raise ValueError(
                    "Stale session revision; fetch the current session before retrying"
                )
            if (
                operation == "play"
                and row["mode"] != "running"
                and db.execute(
                    "SELECT count(*) FROM live_sessions WHERE mode='running'"
                ).fetchone()[0]
                >= 4
            ):
                raise ValueError("At most four sessions may play simultaneously")
            state = EpisodeState.model_validate_json(row["checkpoint"])
            state, frame, mode, rate, reason = apply_action(
                state, row["mode"], row["rate"], operation, payload, self.engine
            )
            revision = expected_revision + 1
            receipt = self.receipt(session_id, revision, state, mode, rate, reason)
            db.execute(
                "UPDATE live_sessions SET revision=?, mode=?, rate=?, reason=?, checkpoint=? WHERE id=?",
                (revision, mode, rate, reason, state.model_dump_json(), session_id),
            )
            if frame is not None:
                db.execute(
                    "INSERT INTO live_frames VALUES (?, ?, ?)",
                    (session_id, state.now_s, encode(frame)),
                )
            db.execute(
                "INSERT INTO live_actions VALUES (?, ?, ?, ?, ?, ?, ?)",
                (
                    session_id,
                    revision,
                    request_id,
                    digest,
                    operation,
                    encode(payload),
                    encode(receipt),
                ),
            )
            return receipt

    def system_action(self, session_id, revision, operation, reason=None):
        if operation not in {"auto_tick", "restart_pause", "worker_error"}:
            raise ValueError("Unknown system operation")
        payload = {"reason": reason}
        return self._mutate(
            session_id,
            f"system:{operation}:{revision}",
            revision,
            operation,
            payload,
            canonical_hash({"revision": revision, "operation": operation, "payload": payload}),
        )

    def running(self):
        with self.connect() as db:
            return [
                dict(row)
                for row in db.execute(
                    "SELECT id, revision, rate FROM live_sessions WHERE mode='running' ORDER BY id"
                )
            ]

    def restart_paused(self):
        for row in self.running():
            self.system_action(
                row["id"], row["revision"], "restart_pause", "Server restarted; resume explicitly"
            )

    def read(self, session_id, *, simulation=False):
        with self.connect() as db:
            row = self.find(db, session_id)
            state = EpisodeState.model_validate_json(row["checkpoint"])
            result = {
                **self.receipt(
                    session_id, row["revision"], state, row["mode"], row["rate"], row["reason"]
                ),
                "title": state.config.title,
                "horizon_s": state.config.horizon_s,
                "observation": controller_view(state),
                "control": state.control.model_dump(mode="json"),
                "control_settings": state.config.control.model_dump(mode="json"),
            }
            if simulation:
                result["simulation"] = {
                    "physical": state.physical.model_dump(mode="json"),
                    "electrical": state.last_electrical,
                    "solver_error": state.last_error,
                    "scheduled_events": [q.model_dump(mode="json") for q in state.future],
                }
            return result

    def list(self):
        with self.connect() as db:
            return [
                dict(row)
                for row in db.execute(
                    "SELECT id, created_at, revision, mode, rate FROM live_sessions ORDER BY created_at DESC LIMIT 100"
                )
            ]

    def export(self, session_id):
        with self.connect() as db:
            row = self.find(db, session_id)
            state = json.loads(row["checkpoint"])
            actions = [
                {
                    "revision": r["revision"],
                    "operation": r["operation"],
                    "payload": json.loads(r["payload"]),
                }
                for r in db.execute(
                    "SELECT * FROM live_actions WHERE session_id=? ORDER BY revision", (session_id,)
                )
            ]
            frames = [
                json.loads(r["payload"])
                for r in db.execute(
                    "SELECT payload FROM live_frames WHERE session_id=? ORDER BY tick",
                    (session_id,),
                )
            ]
            record = {
                "kind": "live-episode",
                "schema_version": 1,
                "id": session_id,
                "created_at": row["created_at"],
                "definition": json.loads(row["definition"]),
                "manifest": state["manifest"],
                "actions": actions,
                "frames": frames,
                "final": {
                    "checkpoint": state,
                    "revision": row["revision"],
                    "mode": row["mode"],
                    "rate": row["rate"],
                    "reason": row["reason"],
                },
            }
            return {**record, "content_sha256": canonical_hash(record)}


def create_session(path, request):
    return SessionStore(path, initialize=False).create(request)


def mutate_session(path, session_id, request):
    return SessionStore(path, initialize=False).mutate(session_id, request)


def tick_session(path, session_id, revision):
    return SessionStore(path, initialize=False).system_action(session_id, revision, "auto_tick")


def replay_episode(record):
    if record.get("kind") != "live-episode" or record.get("schema_version") != 1:
        raise ValueError("Expected a live-episode export")
    if record.get("content_sha256") != canonical_hash(
        {k: v for k, v in record.items() if k != "content_sha256"}
    ):
        raise ValueError("Episode checksum mismatch")
    engine = ElectricalEngine()
    state, frame = start_episode(EpisodeConfig.model_validate(record["definition"]), engine)
    if state.manifest != record["manifest"]:
        raise ValueError(
            "Strict episode replay requires the recorded source, model and OpenDSS version"
        )
    frames, mode, rate, reason = [frame], "paused", 1, state.last_error
    for revision, action in enumerate(record["actions"], 1):
        if action["revision"] != revision:
            raise ValueError("Episode action revisions are not contiguous")
        state, frame, mode, rate, reason = apply_action(
            state, mode, rate, action["operation"], action["payload"], engine
        )
        if frame is not None:
            frames.append(frame)
    final = {
        "checkpoint": state.model_dump(mode="json"),
        "revision": len(record["actions"]),
        "mode": mode,
        "rate": rate,
        "reason": reason,
    }
    differences = _differences(record["frames"], frames, "frames") + _differences(
        record["final"], final, "final"
    )
    return {
        "matched": not differences,
        "differences": differences,
        "ticks": state.now_s,
        "native_snapshots": len(frames),
        "kind": "strict_episode_replay",
    }
