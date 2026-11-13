"""Portable verification reports and fingerprints of the files under test."""

import hashlib
import json
import os
import shutil
import sys
from pathlib import Path


def is_runtime_database(path):
    """SQLite runtime state and journals are never release verification inputs."""
    name = Path(path).name.lower()
    for suffix in ("-wal", "-shm", "-journal"):
        if name.endswith(suffix):
            name = name.removesuffix(suffix)
            break
    return Path(name).suffix in {".sqlite", ".sqlite3", ".db"}


def _require(condition, message):
    if not condition:
        raise ValueError(message)


def selected_files(root):
    ignored = {
        ".git",
        ".venv",
        "venv",
        "node_modules",
        "__pycache__",
        ".pytest_cache",
        ".ruff_cache",
        "var",
        "test-results",
        "playwright-report",
        "build",
        ".mypy_cache",
        ".coverage",
    }
    top_files = {
        "README.md",
        "SETUP.md",
        "DEVELOPMENT.md",
        "CONTRIBUTING.md",
        "SECURITY.md",
        "LICENSE",
        "LICENSE.md",
        "LICENSE.txt",
        "NOTICE",
        "NOTICE.md",
        "NOTICE.txt",
        "COPYING",
        "pyproject.toml",
        "requirements-dev.lock",
        ".gitignore",
        ".gitattributes",
    }
    frontend_files = {
        "package.json",
        "package-lock.json",
        "tsconfig.json",
        "vite.config.ts",
        "playwright.config.ts",
        "prettier.config.mjs",
        "index.html",
        "THIRD_PARTY_NOTICES.txt",
    }
    for directory, dirs, names in os.walk(root):
        dirs[:] = sorted(d for d in dirs if d not in ignored and not d.endswith(".egg-info"))
        for child in dirs:
            _require(
                not (Path(directory) / child).is_symlink(),
                "Symlinked source directory: " + str(Path(directory) / child),
            )
        for name in sorted(names):
            path = Path(directory) / name
            rel = path.relative_to(root)
            # --data-dir may put runtime state outside var/. Exclude SQLite
            # databases and their live journals wherever they were created.
            if is_runtime_database(path):
                continue
            if path.suffix in {".pyc", ".tsbuildinfo", ".tmp"} or name in {
                "RELEASE_MANIFEST.json",
                "progress.json",
            }:
                continue
            if (
                rel.parts[:2] == ("docs", "verification")
                and rel.as_posix() != "docs/verification/summary.json"
            ):
                continue
            if (
                rel.parts[0]
                in {
                    "backend",
                    "docs",
                    "experiments",
                    "scripts",
                    "examples",
                    ".github",
                }
                or rel.as_posix() in top_files
                or (
                    rel.parts[0] == "frontend"
                    and (
                        (len(rel.parts) == 2 and name in frontend_files)
                        or (len(rel.parts) > 2 and rel.parts[1] in {"src", "tests"})
                    )
                )
            ):
                _require(not path.is_symlink(), "Unexpected symlink in deliverable: " + str(rel))
                _require(
                    not name.startswith(".env") or name == ".env.example",
                    "Environment file in deliverable: " + str(rel),
                )
                yield path


def browser_counts(path):
    """Count completed Playwright cases; never infer success from console text."""
    report = json.loads(Path(path).read_text(encoding="utf-8"))
    counts = {"passed": 0, "failed": 0, "skipped": 0, "errors": 0, "flaky": 0}
    stats = report["stats"]
    outcomes = {key: 0 for key in ("expected", "unexpected", "skipped", "flaky")}
    if any(type(stats[k]) is not int or stats[k] < 0 for k in outcomes):
        raise ValueError("Browser report has invalid outcome totals")

    def cases(suites):
        for suite in suites:
            for spec in suite.get("specs", []):
                yield from spec["tests"]
            yield from cases(suite.get("suites", []))

    for case in cases(report["suites"]):
        status = case["status"]
        if status not in outcomes:
            raise ValueError("Browser case has no final outcome")
        outcomes[status] += 1
        results = case["results"]
        if status == "skipped":
            counts["skipped"] += 1
        elif not results or any(r["status"] == "interrupted" for r in results):
            counts["errors"] += 1
        elif (
            status == "expected"
            and case["expectedStatus"] == "passed"
            and all(r["status"] == "passed" for r in results)
        ):
            counts["passed"] += 1
        else:
            counts["failed"] += 1
            counts["flaky"] += int(status == "flaky")
    if outcomes != {key: stats[key] for key in outcomes} or not sum(outcomes.values()):
        raise ValueError("Browser report is empty or its totals do not match its cases")
    counts["errors"] += len(report["errors"])
    return counts


def verification_inputs(root):
    """Sign the delivered source, documentation and assets using one inventory."""
    root = Path(root).resolve()
    return {
        path.relative_to(root).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in sorted(selected_files(root))
        # This generated report embeds the input map and cannot sign itself.
        if path.relative_to(root).as_posix() != "docs/verification/summary.json"
    }


def frontend_build(root):
    root = Path(root).resolve()
    return {
        p.relative_to(root).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
        for p in sorted((root / "frontend/dist").rglob("*"))
        if p.is_file()
    }


def portable_text(text, root, output=None):
    """Replace machine-specific absolute paths without altering result values."""
    replacements = [(str(Path(root).resolve()), "<project>")]
    if output is not None:
        replacements.append((str(Path(output).resolve()), "<verification>"))
    for prefix in {sys.base_prefix, sys.base_exec_prefix}:
        replacements.append((str(Path(prefix).resolve()), "<python-runtime>"))
    for executable in ("npm", "npm.cmd", "node"):
        command = shutil.which(executable)
        if command:
            replacements.append((command, executable))
            replacements.append((str(Path(command).resolve()), executable))
    for original, replacement in sorted(set(replacements), key=lambda p: len(p[0]), reverse=True):
        text = text.replace(original, replacement)
        text = text.replace(original.replace("\\", "\\\\"), replacement)
    return text
