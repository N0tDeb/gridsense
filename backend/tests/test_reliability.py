"""Worker lifetime, input validation, and replay integrity contracts."""

import asyncio
import json
import os
import subprocess
import sys
import sysconfig
import threading
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures.process import BrokenProcessPool
from importlib.resources import files
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from gridsense.api import compute_in_pool
from gridsense.cases import PortableCase
from gridsense.controllers import CONTROLLERS, PlanningView
from gridsense.domain import Action, Operation, Scenario
from gridsense.electrical import ElectricalEngine
from gridsense.network import initial_state
from gridsense.plants import plant_for, planning_view
from gridsense.regression import evaluate_case
from gridsense.service import evaluate
from gridsense.storage import IncidentStore


def test_cancelled_request_keeps_capacity_until_worker_finishes():
    async def check():
        started, release = threading.Event(), threading.Event()
        with ThreadPoolExecutor(max_workers=1) as pool:
            app = SimpleNamespace(state=SimpleNamespace(pool=pool, slots=asyncio.Semaphore(1)))

            def work():
                started.set()
                if not release.wait(5):
                    raise TimeoutError("test worker was not released")
                return 42

            task = asyncio.create_task(compute_in_pool(app, work))
            try:

                async def wait_started():
                    while not started.is_set():
                        await asyncio.sleep(0.001)

                await asyncio.wait_for(wait_started(), 2)
                task.cancel()
                with pytest.raises(asyncio.CancelledError):
                    await task
                # Running executor work survives caller cancellation.
                assert app.state.slots.locked()
                with pytest.raises(HTTPException) as error:
                    await compute_in_pool(app, lambda: "must not be queued")
                assert error.value.status_code == 503
            finally:
                release.set()
            assert await asyncio.wait_for(compute_in_pool(app, lambda: 43), 2) == 43
            assert not app.state.slots.locked()

    asyncio.run(check())


def test_worker_failure_releases_capacity_and_reports_conflict():
    async def check():
        with ThreadPoolExecutor(max_workers=1) as pool:
            app = SimpleNamespace(state=SimpleNamespace(pool=pool, slots=asyncio.Semaphore(1)))

            def invalid():
                raise ValueError("incompatible replay")

            with pytest.raises(HTTPException) as error:
                await compute_in_pool(app, invalid)
            assert error.value.status_code == 409
            assert await compute_in_pool(app, lambda: 7) == 7

    asyncio.run(check())


def test_broken_executor_does_not_leak_capacity():
    class Broken:
        def submit(self, *args):
            raise BrokenProcessPool("worker unavailable")

    async def check():
        app = SimpleNamespace(state=SimpleNamespace(pool=Broken(), slots=asyncio.Semaphore(1)))
        with pytest.raises(HTTPException) as error:
            await compute_in_pool(app, int, "7")
        assert error.value.status_code == 503
        assert not app.state.slots.locked()

    asyncio.run(check())


@pytest.mark.parametrize("value", [[], None, "invalid", False, 0])
def test_cli_rejects_nonobject_case_without_creating_default_run(tmp_path, value):
    source = tmp_path / "invalid.json"
    source.write_text(json.dumps(value), encoding="utf-8")
    data = tmp_path / "data"
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "gridsense.cli",
            "regress",
            "--file",
            str(source),
            "--data-dir",
            str(data),
        ],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 2 and "expected a JSON object" in result.stderr
    assert "Traceback" not in result.stderr and not data.exists()


@pytest.fixture(scope="module")
def ascii_import_paths():
    if os.name != "posix":
        yield None
        return
    # Forced ASCII decoding cannot resolve a Unicode editable-install mapping
    # or extension path. Isolate those paths so these cases test the JSON and
    # native-CWD contracts, even when the checkout/venv itself uses Unicode.
    with TemporaryDirectory(prefix="gridsense-locale-") as directory:
        root = Path(directory)
        source = root / "source"
        source.mkdir()
        (source / "gridsense").symlink_to(Path(files("gridsense")), target_is_directory=True)
        dependencies = root / "dependencies"
        dependencies.symlink_to(sysconfig.get_path("purelib"), target_is_directory=True)
        yield os.pathsep.join((str(source), str(dependencies)))


def test_cli_reads_utf8_bom_case_under_ascii_locale(tmp_path, ascii_import_paths):
    source, output = tmp_path / "case.json", tmp_path / "result.json"
    source.write_text(
        json.dumps({"title": "Restoration café परीक्षण"}, ensure_ascii=False), encoding="utf-8-sig"
    )
    env = {**os.environ, "PYTHONUTF8": "0", "PYTHONCOERCECLOCALE": "0", "LC_ALL": "C"}
    if ascii_import_paths:
        env["PYTHONPATH"] = ascii_import_paths
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "gridsense.cli",
            "regress",
            "--file",
            str(source),
            "--data-dir",
            str(tmp_path / "data"),
            "--output",
            str(output),
        ],
        env=env,
        # Isolate JSON decoding from the native backend's POSIX locale/CWD limit.
        cwd=source.anchor,
        capture_output=True,
    )
    assert result.returncode == 0, result.stderr
    assert (
        json.loads(output.read_text(encoding="utf-8"))["request"]["case"]["title"]
        == "Restoration café परीक्षण"
    )


@pytest.mark.parametrize("python_utf8", ["0", "1"])
def test_cli_rejects_unsupported_native_locale_before_import(
    tmp_path, python_utf8, ascii_import_paths
):
    directory = tmp_path / "GridSense Δ"
    directory.mkdir()
    result = subprocess.run(
        [sys.executable, "-m", "gridsense.cli", "--help"],
        cwd=directory,
        env={
            **os.environ,
            "LC_ALL": "C",
            "PYTHONCOERCECLOCALE": "0",
            "PYTHONUTF8": python_utf8,
            **({"PYTHONPATH": ascii_import_paths} if ascii_import_paths else {}),
        },
        capture_output=True,
        timeout=30,
    )
    if os.name == "posix":
        assert result.returncode == 1, result.stderr
        assert b"GridSense needs a UTF-8 locale" in result.stderr
        assert b"LC_ALL=C.UTF-8" in result.stderr
        assert b"Fatal Python error" not in result.stderr
    else:
        # POSIX locale variables do not define Windows filesystem encoding.
        assert result.returncode == 0, result.stderr


def test_cli_solves_from_unicode_directory_with_utf8_locale(tmp_path):
    directory = tmp_path / "GridSense Δ"
    directory.mkdir()
    source, output = directory / "case.json", directory / "result.json"
    source.write_text(
        json.dumps({"title": "Restoration café परीक्षण"}, ensure_ascii=False), encoding="utf-8-sig"
    )
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "gridsense.cli",
            "regress",
            "--file",
            str(source),
            "--data-dir",
            str(directory / "data"),
            "--output",
            str(output),
        ],
        cwd=directory,
        env={**os.environ, "LC_ALL": "C.UTF-8", "PYTHONUTF8": "1"},
        capture_output=True,
        timeout=30,
    )
    assert result.returncode == 0, result.stderr
    assert json.loads(output.read_text(encoding="utf-8"))["accepted"]
    assert json.loads(output.read_text(encoding="utf-8"))["request"]["case"]["title"] == (
        "Restoration café परीक्षण"
    )


def test_temporal_cli_rejects_excessive_budget_instead_of_clamping(tmp_path):
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "gridsense.cli",
            "temporal",
            "--budget",
            "33",
            "--data-dir",
            str(tmp_path / "data"),
        ],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 2 and "32" in result.stderr
    assert not (tmp_path / "data").exists()


def test_incident_cli_replay_uses_failure_exit_code(tmp_path):
    incident = evaluate(Scenario())
    incident["alternatives"][1]["result"]["served_kw"] += 10
    IncidentStore(tmp_path / "gridsense.sqlite3").save(incident)
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "gridsense.cli",
            "replay",
            "--incident",
            incident["id"],
            "--data-dir",
            str(tmp_path),
        ],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 1 and not json.loads(result.stdout)["matched"]
    missing = subprocess.run(
        [
            sys.executable,
            "-m",
            "gridsense.cli",
            "replay",
            "--incident",
            "missing",
            "--data-dir",
            str(tmp_path),
        ],
        capture_output=True,
        text=True,
    )
    assert missing.returncode == 2 and "Traceback" not in missing.stderr


@pytest.mark.parametrize("fault", ["632670", "671692"])
def test_ieee_controller_inputs_are_independent_of_hidden_demand(fault):
    case = PortableCase(
        feeder="ieee13",
        fault=fault,
        scenario=Scenario(load_a=0.8, load_b=0.8, reported_b=0.8, uncertainty_pct=20),
    )
    changed = case.model_copy(update={"scenario": case.scenario.model_copy(update={"load_a": 1.1})})
    first, second = plant_for(case), plant_for(changed)
    view = planning_view(first, "2026-01-01T12:00:00+00:00")
    assert view == planning_view(second, "2026-01-01T12:00:00+00:00")
    policy = CONTROLLERS["nominal-v1"]
    low = evaluate_case(case, policy, plant=first, view=view)
    high = evaluate_case(changed, policy, plant=second, view=view)
    assert low["action"] == high["action"]
    assert low["result"]["served_kw"] != high["result"]["served_kw"]
    assert policy.select(
        PlanningView(view.observation, tuple(reversed(view.candidates)))
    ) == policy.select(view)


def test_invalid_intermediate_electrical_state_cannot_be_hidden_by_safe_final_state():
    engine = ElectricalEngine()
    state = initial_state({"a": 1, "b": 1.5, "c": 0.9})
    action = Action(
        id="unsafe-order",
        label="Close tie before reducing donor load",
        operations=(Operation(line="tie_b", closed=True), Operation(line="seg_b", closed=False)),
    )
    outcome = engine.execute(state, action)
    assert not outcome.steps[0].feasible
    assert outcome.steps[-1].feasible and engine.solve(outcome.final_state).feasible
    assert not outcome.result.feasible
    assert any(v.element == "feed_b" for v in outcome.result.violations)


def test_repeated_solves_preserve_served_unserved_accounting_and_native_state():
    engine = ElectricalEngine()
    state = initial_state({"a": 1, "b": 0.7, "c": 0.9})
    before = engine.solve(state)
    action = Action(id="close", label="close", operations=(Operation(line="tie_b", closed=True),))
    after = engine.execute(state, action).result
    assert engine.solve(state) == before
    for result in (before, after):
        assert result.served_kw + result.unserved_kw == pytest.approx(result.requested_kw)
        assert result.served_kw == pytest.approx(
            sum(r["served_kw"] for r in result.load_measurements)
        )
        assert all(r["served_kw"] == 0 for r in result.load_measurements if not r["energized"])
