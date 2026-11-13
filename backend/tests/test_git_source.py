"""Git source preparation must preserve evidence and exclude live storage."""

import sqlite3
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture
def repository(tmp_path):
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True, capture_output=True)
    for name in (".gitignore", ".gitattributes"):
        (tmp_path / name).write_bytes((ROOT / name).read_bytes())
    return tmp_path


@pytest.mark.parametrize("extension", [".sqlite", ".sqlite3", ".db"])
def test_git_excludes_live_database_and_journals_in_custom_directory(repository, extension):
    path = repository / "backend/local-data" / ("gridsense" + extension)
    path.parent.mkdir(parents=True)
    source = repository / "backend/example.py"
    source.write_text("value = 1\n")
    with sqlite3.connect(path) as db:
        db.execute("PRAGMA journal_mode=WAL")
        db.execute("CREATE TABLE session_state (value TEXT)")
        db.execute("INSERT INTO session_state VALUES ('runtime state')")
        db.commit()
        files = {p.relative_to(repository).as_posix() for p in path.parent.iterdir()}
        assert len(files) == 3
        ignored = subprocess.run(
            ["git", "check-ignore", "--stdin"],
            cwd=repository,
            input="\n".join(sorted(files)) + "\n",
            text=True,
            capture_output=True,
            check=True,
        )
        assert set(ignored.stdout.splitlines()) == files
        kept = subprocess.run(
            ["git", "check-ignore", "--quiet", "backend/example.py"],
            cwd=repository,
            capture_output=True,
            check=False,
        )
        assert kept.returncode == 1


@pytest.mark.parametrize("autocrlf", ["true", "false"])
def test_git_preserves_real_csv_evidence_bytes_under_newline_modes(repository, autocrlf):
    subprocess.run(["git", "config", "core.autocrlf", autocrlf], cwd=repository, check=True)
    names = [
        "experiments/challenge_results/outcomes.csv",
        "experiments/challenge_discovery/outcomes.csv",
        "backend/gridsense/circuits/ieee13/IEEE13Node_BusXY.csv",
    ]
    for name in names:
        destination = repository / name
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes((ROOT / name).read_bytes())
    subprocess.run(["git", "add", ".gitattributes", *names], cwd=repository, check=True)
    for name in names:
        stored = subprocess.check_output(["git", "show", ":" + name], cwd=repository)
        assert stored == (ROOT / name).read_bytes()


@pytest.mark.parametrize("name", [".gitignore", ".gitattributes"])
def test_source_protection_configuration_changes_invalidate_verification(
    repository, monkeypatch, name
):
    monkeypatch.syspath_prepend(str(ROOT / "scripts"))
    from release_support import verification_inputs

    (repository / "pyproject.toml").write_text("[project]\nname='example'\n")
    (repository / "requirements-dev.lock").write_text("dependency==1\n")
    before = verification_inputs(repository)
    rule = (
        "!backend/local-data/gridsense.sqlite3\n"
        if name == ".gitignore"
        else "experiments/**/*.csv text eol=lf\n"
    )
    with (repository / name).open("a") as target:
        target.write(rule)
    assert verification_inputs(repository) != before
