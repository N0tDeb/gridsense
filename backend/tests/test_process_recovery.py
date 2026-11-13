"""Abrupt child-process death at real SQLite commit boundaries, with native ticks."""

import json
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor

import pytest

from gridsense.electrical import ElectricalEngine
from gridsense.episodes import EpisodeConfig
from gridsense.session_store import CreateSession, SessionMutation, SessionStore, replay_episode


CHILD = r"""
import json, sys
from contextlib import contextmanager
from gridsense.session_store import SessionStore, SessionMutation

path, session_id, boundary, mode, revision = sys.argv[1:]
store = SessionStore(path)
original = store.connect

def stop_at_boundary():
    print(json.dumps({"boundary": boundary, "ready": True}), flush=True)
    sys.stdin.readline()  # Parent kills the process; no exception or graceful cleanup.
    raise RuntimeError("Parent did not terminate the child")

@contextmanager
def connected(*, write=False):
    with original(write=write) as db:
        yield db
        if write and boundary == "before_commit":
            stop_at_boundary()
    if write and boundary == "after_commit":
        stop_at_boundary()

store.connect = connected
if mode == "running":
    store.system_action(session_id, int(revision), "auto_tick")
else:
    store.mutate(session_id, SessionMutation(
        request_id="lost-response", expected_revision=int(revision), operation="step"))
"""


@pytest.fixture(scope="module")
def engine():
    return ElectricalEngine()


@pytest.mark.parametrize(
    "boundary,mode",
    [
        ("before_commit", "paused"),
        ("after_commit", "paused"),
        ("after_commit", "running"),
    ],
)
def test_killed_native_tick_rolls_back_or_recovers_exactly_once(tmp_path, engine, boundary, mode):
    # Exercise Unicode and spaces without relying on shell argument splitting.
    path = tmp_path / "saved sessions Δ" / "grid state.sqlite3"
    store = SessionStore(path, engine=engine)
    created = store.create(
        CreateSession(
            request_id="create",
            config=EpisodeConfig.model_validate(
                {
                    "horizon_s": 8,
                    "control": {"policy": "nominal"},
                    "events": [
                        {
                            "kind": "outage",
                            "at_s": 1,
                            "incident_id": "trip",
                            "equipment_kind": "line",
                            "equipment": "feed_a",
                        },
                        {"kind": "repair", "at_s": 5, "incident_id": "trip"},
                    ],
                }
            ),
        )
    )
    session_id = created["id"]
    if mode == "running":
        created = store.mutate(
            session_id, SessionMutation(request_id="play", expected_revision=0, operation="play")
        )
    before = store.export(session_id)
    with (tmp_path / "child-errors.txt").open("w+", encoding="utf-8") as errors:
        child = subprocess.Popen(
            [
                sys.executable,
                "-u",
                "-c",
                CHILD,
                str(path),
                session_id,
                boundary,
                mode,
                str(created["revision"]),
            ],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=errors,
            text=True,
            encoding="utf-8",
        )
        with ThreadPoolExecutor(max_workers=1) as reader:
            line = reader.submit(child.stdout.readline)
            try:
                marker = line.result(timeout=30)
                errors.flush()
                errors.seek(0)
                assert marker, errors.read()
                assert json.loads(marker) == {"boundary": boundary, "ready": True}
            finally:
                child.kill()
                child.wait(timeout=10)
                child.stdin.close()
                child.stdout.close()
        assert child.returncode != 0

    recovered = SessionStore(path, engine=engine)
    with recovered.connect() as db:
        assert db.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        assert not db.execute("PRAGMA foreign_key_check").fetchall()
    saved = recovered.export(session_id)
    if boundary == "before_commit":
        assert saved == before  # No new frame, command, action, receipt or checkpoint.
    else:
        assert saved["final"]["checkpoint"]["now_s"] == 1
        commands = saved["final"]["checkpoint"]["control"]["commands"]
        assert len(commands) == 1 and next(iter(commands.values()))["status"] == "pending"

    def retry():
        if mode == "running":
            return recovered.system_action(session_id, created["revision"], "auto_tick")
        return recovered.mutate(
            session_id,
            SessionMutation(
                request_id="lost-response", expected_revision=created["revision"], operation="step"
            ),
        )

    receipt = retry()
    once = recovered.export(session_id)
    assert retry() == receipt and recovered.export(session_id) == once
    recovered.restart_paused()
    receipt = recovered.read(session_id)
    assert receipt["mode"] == "paused" and receipt["at_s"] == 1
    paused = recovered.export(session_id)
    recovered.restart_paused()
    assert recovered.export(session_id) == paused
    while receipt["at_s"] < 8:
        receipt = recovered.mutate(
            session_id,
            SessionMutation(
                request_id=f"resume-{receipt['at_s']}",
                expected_revision=receipt["revision"],
                operation="step",
            ),
        )
    final = recovered.export(session_id)
    assert [f["at_s"] for f in final["frames"]] == list(range(9))
    assert final["frames"][-1]["electrical"]["unserved_kw"] < 0.1
    assert len(final["final"]["checkpoint"]["control"]["commands"]) == 3
    assert replay_episode(final)["matched"]
