import asyncio
import copy
import sqlite3
import time
from concurrent.futures import ThreadPoolExecutor

import pytest
from gridsense.electrical import ElectricalEngine
from gridsense.episodes import EpisodeConfig, OutageEvent, RepairEvent, canonical_hash
from gridsense.session_api import pace_sessions
from gridsense.session_store import CreateSession, SessionMutation, SessionStore, replay_episode


@pytest.fixture(scope="module")
def engine():
    return ElectricalEngine()


@pytest.fixture
def store(tmp_path, engine):
    return SessionStore(tmp_path / "sessions.sqlite3", engine=engine)


def create(store, horizon=4, request_id="create"):
    return store.create(
        CreateSession(request_id=request_id, config=EpisodeConfig(horizon_s=horizon))
    )


def act(store, receipt, operation="step", **kwargs):
    return store.mutate(
        receipt["id"],
        SessionMutation(
            request_id="request-" + str(receipt["revision"]),
            expected_revision=receipt["revision"],
            operation=operation,
            **kwargs,
        ),
    )


def test_idempotent_creation_and_actions_return_original_receipts(store):
    first = create(store)
    request = SessionMutation(request_id="step", expected_revision=0, operation="step")
    stepped = store.mutate(first["id"], request)
    assert create(store) == first
    assert store.mutate(first["id"], request) == stepped
    assert store.read(first["id"])["at_s"] == 1
    exported = store.export(first["id"])
    assert len(exported["frames"]) == 2 and len(exported["actions"]) == 1
    with pytest.raises(ValueError, match="another payload"):
        store.mutate(first["id"], request.model_copy(update={"operation": "pause"}))
    with pytest.raises(ValueError, match="another payload"):
        create(store, horizon=5)
    with pytest.raises(ValueError, match="Stale"):
        act(store, first)


def test_tick_action_and_checkpoint_rollback_together_on_commit_path_failure(store):
    first = create(store)
    before = store.export(first["id"])
    with store.connect(write=True) as db:
        db.execute(
            "CREATE TRIGGER fail_action BEFORE INSERT ON live_actions BEGIN SELECT RAISE(ABORT, 'forced write failure'); END"
        )
    with pytest.raises(sqlite3.IntegrityError, match="forced write failure"):
        act(store, first)
    assert store.export(first["id"]) == before
    with store.connect(write=True) as db:
        db.execute("DROP TRIGGER fail_action")
    assert act(store, first)["at_s"] == 1


def test_unexpected_native_exception_rolls_back_every_record(store, engine, monkeypatch):
    first = create(store)
    before = store.export(first["id"])

    def fail(_):
        raise RuntimeError("native job failed")

    monkeypatch.setattr(engine, "solve", fail)
    with pytest.raises(RuntimeError, match="native job failed"):
        act(store, first)
    assert store.export(first["id"]) == before


def test_concurrent_same_revision_has_exactly_one_committed_tick(store):
    first = create(store)

    def attempt(request_id):
        try:
            return store.mutate(
                first["id"],
                SessionMutation(request_id=request_id, expected_revision=0, operation="step"),
            )
        except ValueError as exc:
            return str(exc)

    with ThreadPoolExecutor(max_workers=2) as workers:
        results = list(workers.map(attempt, ("one", "two")))
    assert sum(isinstance(r, dict) for r in results) == 1
    assert sum(isinstance(r, str) and "Stale" in r for r in results) == 1
    assert store.read(first["id"])["at_s"] == 1
    assert len(store.export(first["id"])["actions"]) == 1


def test_restart_pauses_without_wall_clock_catchup_and_replays(store):
    first = act(store, create(store), "play", rate=10)
    first = store.system_action(first["id"], first["revision"], "auto_tick")
    restarted = SessionStore(store.path, engine=store.engine)
    restarted.restart_paused()
    state = restarted.read(first["id"])
    assert state["at_s"] == 1 and state["mode"] == "paused"
    assert state["revision"] == first["revision"] + 1
    assert "restarted" in state["pause_reason"]
    exported = restarted.export(first["id"])
    restarted.restart_paused()
    assert restarted.export(first["id"]) == exported
    assert replay_episode(exported)["matched"]


def test_playback_rate_changes_pacing_not_physical_frames(store):
    frames = []
    for rate in (1, 5, 10):
        receipt = create(store, horizon=2, request_id="create-" + str(rate))
        receipt = act(store, receipt, "play", rate=rate)
        with pytest.raises(ValueError, match="paused"):
            act(store, receipt)
        for _ in range(2):
            receipt = store.system_action(receipt["id"], receipt["revision"], "auto_tick")
        assert receipt["mode"] == "paused" and receipt["at_s"] == 2
        with pytest.raises(ValueError, match="completed"):
            act(store, receipt, "play")
        with pytest.raises(ValueError, match="horizon"):
            act(store, receipt)
        exported = store.export(receipt["id"])
        assert replay_episode(exported)["matched"]
        frames.append(exported["frames"])
    assert frames[0] == frames[1] == frames[2]


def test_playback_session_limit_is_explicit(store):
    for i in range(4):
        act(store, create(store, request_id=f"create-{i}"), "play")
    fifth = create(store, request_id="fifth")
    with pytest.raises(ValueError, match="four sessions"):
        act(store, fifth, "play")


def test_scheduled_actions_replay_from_the_same_initial_definition(store):
    receipt = create(store)
    receipt = act(
        store,
        receipt,
        "schedule",
        events=(
            OutageEvent(at_s=1, incident_id="outage", equipment_kind="line", equipment="feed_a"),
            RepairEvent(at_s=3, incident_id="outage"),
        ),
    )
    for _ in range(4):
        receipt = act(store, receipt)
    exported = store.export(receipt["id"])
    assert exported["definition"]["events"] == []
    assert len(exported["frames"]) == 5 and exported["frames"][1]["electrical"]["unserved_kw"] > 999
    result = replay_episode(exported)
    assert result["matched"] and result["ticks"] == 4 and result["native_snapshots"] == 5


def test_export_separates_controller_observations_from_simulation_truth(store):
    first = create(store)
    public = store.read(first["id"])
    truth = store.read(first["id"], simulation=True)
    assert "simulation" not in public
    assert set(truth["simulation"]) == {
        "physical",
        "electrical",
        "solver_error",
        "scheduled_events",
    }
    assert truth["observation"] == public["observation"]


def rehash(record):
    record["content_sha256"] = canonical_hash(
        {k: v for k, v in record.items() if k != "content_sha256"}
    )
    return record


def test_strict_replay_detects_changed_results_even_with_a_recomputed_checksum(store):
    receipt = act(store, create(store))
    record = store.export(receipt["id"])
    record["frames"][1]["electrical"]["served_kw"] = -1
    with pytest.raises(ValueError, match="checksum"):
        replay_episode(record)
    result = replay_episode(rehash(record))
    assert not result["matched"] and result["differences"]


@pytest.mark.parametrize("field", ["episode_sha256", "network_sha256", "solver_version"])
def test_strict_replay_rejects_foreign_source_model_and_solver(store, field):
    record = copy.deepcopy(store.export(create(store)["id"]))
    record["manifest"][field] = "foreign"
    with pytest.raises(ValueError, match="recorded source"):
        replay_episode(rehash(record))


def test_nonconvergence_is_committed_as_unknown_and_pauses_playback(store, engine, monkeypatch):
    receipt = act(store, create(store), "play")
    original = engine.solve
    monkeypatch.setattr(
        engine, "solve", lambda physical: original(physical).model_copy(update={"converged": False})
    )
    changed = store.system_action(receipt["id"], receipt["revision"], "auto_tick")
    assert (
        changed["at_s"] == 1
        and changed["mode"] == "paused"
        and "converge" in changed["pause_reason"]
    )
    assert store.export(receipt["id"])["frames"][-1]["electrical"] is None


def test_pacer_slow_work_does_not_catch_up_or_skip_ticks(store):
    receipt = act(store, create(store, horizon=2), "play", rate=10)

    async def exercise():
        starts, ends = [], []
        finished = asyncio.Event()

        async def compute(function, path, session_id, revision):
            starts.append(time.monotonic())
            await asyncio.sleep(0.2)
            result = store.system_action(session_id, revision, "auto_tick")
            ends.append(time.monotonic())
            if result["mode"] == "paused":
                finished.set()
            return result

        task = asyncio.create_task(pace_sessions(store, compute))
        try:
            await asyncio.wait_for(finished.wait(), timeout=5)
        finally:
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
        assert len(starts) == 2 and starts[1] - ends[0] >= 0.09

    asyncio.run(exercise())
    assert [f["at_s"] for f in store.export(receipt["id"])["frames"]] == [0, 1, 2]


def test_pacer_records_unexpected_worker_failure_and_stays_alive(store):
    receipt = act(store, create(store), "play", rate=10)

    async def exercise():
        failed = asyncio.Event()

        async def compute(*args):
            failed.set()
            raise RuntimeError("unexpected worker failure")

        task = asyncio.create_task(pace_sessions(store, compute))
        try:
            await asyncio.wait_for(failed.wait(), timeout=5)
            assert not task.done()
            view = store.read(receipt["id"])
            assert view["mode"] == "paused" and view["at_s"] == 0
            assert "worker failed" in view["pause_reason"]
        finally:
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task

    asyncio.run(exercise())
