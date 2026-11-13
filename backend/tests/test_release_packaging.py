"""Release fingerprints must describe files that are actually delivered."""

import sys
import sqlite3
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))

from package_release import selected_files
from release_support import verification_inputs


def test_monitor_updates_do_not_invalidate_packaged_results(tmp_path):
    for name, content in {
        "pyproject.toml": "[project]\nname='example'\n",
        "requirements-dev.lock": "dependency==1\n",
        "backend/example.py": "value = 1\n",
        "frontend/index.html": "<title>Example</title>\n",
        "frontend/progress.json": '{"completed": 1}\n',
        "experiments/quality_results/results.json": '{"completed": true}\n',
        "experiments/quality_results/progress.json": '{"completed": 8}\n',
    }.items():
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content)

    fingerprints = verification_inputs(tmp_path)
    delivered = {path.relative_to(tmp_path).as_posix() for path in selected_files(tmp_path)}
    assert set(fingerprints) <= delivered

    (tmp_path / "experiments/quality_results/progress.json").write_text('{"completed": 9}\n')
    assert verification_inputs(tmp_path) == fingerprints

    (tmp_path / "experiments/quality_results/results.json").write_text('{"completed": false}\n')
    assert verification_inputs(tmp_path) != fingerprints


@pytest.mark.parametrize("extension", [".sqlite3", ".sqlite", ".db"])
def test_runtime_database_in_custom_data_directory_is_not_packaged(tmp_path, extension):
    for name in ("pyproject.toml", "requirements-dev.lock"):
        (tmp_path / name).write_text("Release configuration\n")
    source = tmp_path / "backend/example.py"
    source.parent.mkdir(parents=True)
    source.write_text("value = 1\n")
    fingerprints = verification_inputs(tmp_path)
    data = tmp_path / "backend/local-data" / ("gridsense" + extension)
    data.parent.mkdir()
    with sqlite3.connect(data) as db:
        db.execute("PRAGMA journal_mode=WAL")
        db.execute("CREATE TABLE session_state (value TEXT)")
        db.execute("INSERT INTO session_state VALUES ('runtime session record')")
        db.commit()
        assert Path(str(data) + "-wal").is_file()
        assert Path(str(data) + "-shm").is_file()
        delivered = {p.relative_to(tmp_path).as_posix() for p in selected_files(tmp_path)}
        assert delivered == {"backend/example.py", "pyproject.toml", "requirements-dev.lock"}
        assert verification_inputs(tmp_path) == fingerprints
        assert set(fingerprints) <= delivered


def test_release_retains_repository_guidance_and_project_license_when_present(tmp_path):
    names = {"README.md", "CONTRIBUTING.md", "SECURITY.md", "LICENSE", "NOTICE"}
    for name in names:
        (tmp_path / name).write_text("Repository guidance\n")
    delivered = {p.relative_to(tmp_path).as_posix() for p in selected_files(tmp_path)}
    assert names <= delivered
