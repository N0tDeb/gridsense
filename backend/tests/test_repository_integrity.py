"""A clean source archive must retain resources and reject broken references."""

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))

from check_repository import check_links, scan_text
from release_support import selected_files, verification_inputs


def test_local_links_must_target_delivered_resources_and_valid_headings(tmp_path):
    readme = tmp_path / "README.md"
    target = tmp_path / "guide.md"
    target.write_text("# Guide\n\n## Run locally\n")
    readme.write_text(
        "[Run](guide.md#run-locally)\n[Asset](missing.svg)\n[Heading](guide.md#absent)\n"
    )
    checked, errors = check_links(tmp_path, [readme], {readme, target})
    assert checked == 3 and len(errors) == 2
    assert any("missing.svg" in error for error in errors)
    assert any("#absent" in error for error in errors)


def test_credential_detection_does_not_disclose_the_matched_value(tmp_path):
    token = "ghp_" + "x" * 36
    source = tmp_path / "config.py"
    source.write_text("credential = " + repr(token))
    errors = scan_text(source, tmp_path)
    assert len(errors) == 1 and "GitHub token" in errors[0]
    assert token not in errors[0]


def test_source_inventory_keeps_tests_and_data_without_generated_copies(tmp_path):
    keep = {
        "frontend/src/App.tsx",
        "backend/tests/test_behavior.py",
        "experiments/results/frames.jsonl.gz",
        "docs/verification/summary.json",
    }
    drop = {
        "frontend/dist/index.html",
        "frontend/node_modules/react/index.js",
        "docs/verification/runtime/capture.png",
        "docs/verification/old-log.txt",
    }
    for name in keep | drop:
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"resource\n")
    assert {p.relative_to(tmp_path).as_posix() for p in selected_files(tmp_path)} == keep


def test_documentation_changes_invalidate_release_verification(tmp_path):
    for name in ("pyproject.toml", "requirements-dev.lock", "README.md"):
        (tmp_path / name).write_text("setup\n")
    before = verification_inputs(tmp_path)
    (tmp_path / "README.md").write_text("different setup\n")
    assert verification_inputs(tmp_path) != before


def test_source_directory_cannot_escape_through_a_symlink(tmp_path):
    outside = tmp_path / "external"
    outside.mkdir()
    backend = tmp_path / "backend"
    backend.mkdir()
    try:
        (backend / "shared").symlink_to(outside, target_is_directory=True)
    except OSError:
        pytest.skip("Directory symlinks are unavailable on this platform")
    with pytest.raises(ValueError, match="Symlinked source directory"):
        list(selected_files(tmp_path))
