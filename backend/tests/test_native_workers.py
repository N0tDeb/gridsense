import asyncio
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from gridsense.api import compute_in_pool, create_app
from gridsense.electrical import ElectricalEngine
from gridsense.network import healthy_state

ROOT = Path(__file__).resolve().parents[2]


def native_job(factor):
    result = ElectricalEngine().solve(healthy_state({"a": factor, "b": 1, "c": 1}))
    return os.getpid(), result.model_dump()


def test_api_releases_each_native_worker_and_preserves_repeatable_results(tmp_path):
    async def exercise():
        app = create_app(tmp_path)
        async with app.router.lifespan_context(app):
            results = [await compute_in_pool(app, native_job, v) for v in (0.9, 1.0, 0.9)]
            assert len({pid for pid, _ in results}) == 3
            assert all(pid != os.getpid() and value["feasible"] for pid, value in results)
            assert results[0][1] == results[2][1]
            assert results[0][1]["served_kw"] < results[1][1]["served_kw"]
            assert not app.state.slots.locked()

    asyncio.run(exercise())


def test_benchmark_process_boundary_preserves_native_cases_and_propagates_failure(monkeypatch):
    monkeypatch.syspath_prepend(str(ROOT / "experiments"))
    from run_quality_benchmark import controller_group, isolated_call

    protocol = json.loads((ROOT / "experiments/protocols/quality.json").read_text())
    direct = controller_group(protocol, "teaching", "feed_a", 100)
    isolated = isolated_call(controller_group, protocol, "teaching", "feed_a", 100)
    assert isolated[:2] == direct[:2]
    assert len(isolated[0]) == 8 and len(isolated[1]) == 24
    with pytest.raises(ValueError):
        isolated_call(int, "invalid")


def test_quality_runner_does_not_replace_existing_evidence(tmp_path):
    sentinel = tmp_path / "results.json"
    sentinel.write_text("existing evidence")
    result = subprocess.run(
        [sys.executable, "experiments/run_quality_benchmark.py", "--output-dir", str(tmp_path)],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=20,
    )
    assert result.returncode == 2 and "not empty" in result.stderr
    assert sentinel.read_text() == "existing evidence"
