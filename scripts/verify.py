"""One-command local/CI verification; preserves every subprocess log.

Install locked dependencies and the Playwright browser using SETUP.md first.
This script never installs packages, edits configuration or changes model data.
"""

import argparse
import json
import os
import platform
import shutil
import subprocess
import sys
import time
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path
from release_support import browser_counts, frontend_build, portable_text, verification_inputs

ROOT = Path(__file__).resolve().parents[1]


def junit_counts(path):
    tree = ET.parse(path).getroot()
    suites = [tree] if tree.tag == "testsuite" else list(tree.iter("testsuite"))
    counts = {"passed": 0, "failed": 0, "skipped": 0, "errors": 0}
    for suite in suites:
        failed, skipped, errors = (int(suite.get(k, 0)) for k in ("failures", "skipped", "errors"))
        counts["failed"] += failed
        counts["skipped"] += skipped
        counts["errors"] += errors
        counts["passed"] += int(suite.get("tests", 0)) - failed - skipped - errors
    return counts


def run_step(name, command, cwd, output, *, expected=0, timeout=600, env=None):
    start = time.perf_counter()
    environment = {
        **os.environ,
        "GRIDSENSE_PYTHON": str(Path(sys.executable).absolute()),
        "PYTHONUTF8": "1",
        **(env or {}),
    }
    path = output / (name + ".txt")
    print(f"Running {name} ...", flush=True)
    with path.open("w", encoding="utf-8") as log:
        try:
            result = subprocess.run(
                command,
                cwd=cwd,
                env=environment,
                stdout=log,
                stderr=subprocess.STDOUT,
                timeout=timeout,
                check=False,
            )
            code, error = result.returncode, None
        except (OSError, subprocess.TimeoutExpired) as exc:
            code, error = None, str(exc)
            log.write("\nVerification runner error: " + error + "\n")
    path.write_text(portable_text(path.read_text(encoding="utf-8"), ROOT, output), encoding="utf-8")
    status = "passed" if code == expected else "failed"
    display = (
        "expected nonzero exit; inspect scientific result"
        if status == "passed" and expected
        else status
    )
    print(f"{name}: {display} (exit {code}); {path}", flush=True)
    return {
        "name": name,
        "command": [portable_text(str(value), ROOT, output) for value in command],
        "cwd": portable_text(str(cwd), ROOT, output),
        "exit_code": code,
        "expected_exit": expected,
        "status": status,
        "error": portable_text(error, ROOT, output) if error else None,
        "elapsed_seconds": time.perf_counter() - start,
        "log": path.name,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=ROOT / "var" / ("verify-" + datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")),
    )
    parser.add_argument(
        "--skip-browser", action="store_true", help="Explicitly mark browser verification skipped"
    )
    parser.add_argument(
        "--campaign", action="store_true", help="Also rerun the complete frozen assurance campaign"
    )
    args = parser.parse_args()
    output = args.output_dir.resolve()
    if output.exists() and any(output.iterdir()):
        parser.error("Output directory is not empty; use a new directory")
    output.mkdir(parents=True, exist_ok=True)
    python = str(Path(sys.executable).absolute())
    inputs_before = verification_inputs(ROOT)
    cli = [python, "-m", "gridsense.cli"]
    rows = []

    def step(name, command, cwd=ROOT, **kwargs):
        row = run_step(name, command, cwd, output, **kwargs)
        rows.append(row)
        return row

    step("dependencies", [python, "-m", "pip", "check"])
    step("repository-integrity", [python, "scripts/check_repository.py"])
    step(
        "python-format",
        [
            python,
            "-m",
            "ruff",
            "format",
            "--check",
            "backend",
            "scripts",
            "examples",
            *[str(p.relative_to(ROOT)) for p in sorted((ROOT / "experiments").glob("*.py"))],
        ],
    )
    step("python-lint", [python, "-m", "ruff", "check", "backend", "scripts", "examples"])
    step(
        "backend",
        [
            python,
            "-m",
            "pytest",
            "backend/tests/",
            "-q",
            "--junitxml=" + str(output / "backend-junit.xml"),
        ],
    )
    step("voltage-reference", [*cli, "validate-feeder"])
    # Preserve the reference failure; a successful test run does not erase it.
    extended = step(
        "extended-reference",
        [
            python,
            "experiments/run_reference_checks.py",
            "--output",
            str(output / "electrical-reference.json"),
        ],
        expected=1,
    )
    reference_passed = None
    if (output / "electrical-reference.json").exists():
        report = json.loads((output / "electrical-reference.json").read_text(encoding="utf-8"))
        reference_passed = report["passed"]
    if extended["status"] == "passed" and reference_passed is not None:
        failures = {r["id"] for r in report["additional_checks"] if not r["passed"]}
        expected_failures = {
            "load-current-675b",
            "load-kw-675b",
            "load-kvar-675b",
            "power-balance-kW",
        }
        if failures != expected_failures or not report["published_voltage"]["passed"]:
            extended["status"] = "failed"
            extended["error"] = "Different reference outcome; inspect without changing tolerances"
        else:
            extended["status"] = "known-reference-mismatch"
            extended["scientific_reference_passed"] = False
    elif extended["status"] == "passed":
        extended["status"] = "failed"
        extended["error"] = "Reference command did not write an evidence report"
    configured = step(
        "configured-pq-reference",
        [
            python,
            "experiments/run_configured_reference.py",
            "--verify-report",
            "experiments/configured_reference_results/results.json",
            "--output",
            str(output / "configured-reference.json"),
        ],
    )
    configured_reference_passed = False
    if configured["status"] == "passed":
        try:
            configured_report = json.loads(
                (output / "configured-reference.json").read_text(encoding="utf-8")
            )
            configured_reference_passed = (
                configured_report["passed"] is True
                and configured_report["passed_checks"] == configured_report["total_checks"] == 56
                and configured_report["native_default_baseline_matched"] is True
            )
            if not configured_reference_passed:
                raise ValueError("Configured reference or native baseline did not match")
        except (OSError, KeyError, TypeError, ValueError) as exc:
            configured["status"] = "failed"
            configured["error"] = str(exc)
    step(
        "model-reference",
        [
            python,
            "experiments/run_model_reference.py",
            "--output",
            str(output / "model-reference.json"),
        ],
    )
    step(
        "reference-settings-sensitivity",
        [
            python,
            "experiments/run_reference_sensitivity.py",
            "--verify-report",
            "experiments/reference_sensitivity_results/results.json",
        ],
    )
    step("equipment-example", [python, "examples/equipment_availability.py"])
    step("live-episode-example", [python, "examples/live_episode.py"])
    step("restoration-episode-example", [python, "examples/restoration_episode.py"])
    step(
        "session-study-consistency",
        [python, "experiments/run_session_benchmark.py", "--verify-report"],
    )
    step(
        "session-challenge-consistency",
        [python, "experiments/run_session_challenge.py", "--verify-report"],
    )
    step("challenge-discovery-consistency", [python, "scripts/check_challenge_discovery.py"])
    step(
        "measurement-refresh-consistency",
        [python, "experiments/run_measurement_refresh.py", "--verify-report"],
    )
    step("evidence-consistency", [python, "scripts/check_evidence.py"])
    step(
        "native-reuse-consistency",
        [python, "experiments/run_native_reuse.py", "--verify-report"],
    )
    for name, command in (
        ("failure-search.json", "reproduce"),
        ("regression.json", "verify-run"),
        ("temporal.json", "verify-run"),
    ):
        step(
            "replay-" + name.removesuffix(".json"),
            [*cli, command, "--file", "experiments/examples/" + name],
        )
    reproducers = sorted((ROOT / "experiments/assurance_results/reproducers").glob("*.json"))
    if not reproducers:
        rows.append(
            {"name": "defect-replay", "status": "failed", "error": "No bundled reproducers found"}
        )
    for path in reproducers:
        step(
            "replay-defect-" + path.stem, [python, "experiments/reproduce_assurance.py", str(path)]
        )
    if args.skip_browser:
        rows.append({"name": "browser", "status": "skipped", "reason": "Explicit --skip-browser"})
    else:
        npm = shutil.which("npm.cmd" if os.name == "nt" else "npm")
        if npm:
            step("frontend-format", [npm, "run", "format:check"], ROOT / "frontend")
            step(
                "browser",
                [npm, "run", "test:e2e"],
                ROOT / "frontend",
                env={"GRIDSENSE_BROWSER_REPORT": str(output / "browser-results.json")},
            )
            step(
                "runtime",
                [npm, "run", "check:runtime", "--", "--output-dir", str(output / "runtime")],
                ROOT / "frontend",
            )
        else:
            rows.append(
                {"name": "browser", "status": "failed", "error": "npm is not installed/on PATH"}
            )
    step(
        "process-restart",
        [python, "scripts/check_restart.py", "--output-dir", str(output / "restart")],
    )
    if args.campaign:
        step(
            "assurance-campaign",
            [
                python,
                "experiments/run_assurance_benchmark.py",
                "--output-dir",
                str(output / "campaign"),
            ],
        )
    report = {
        "verified_at": datetime.now(timezone.utc).isoformat(),
        "python": platform.python_version(),
        "platform": platform.platform(),
        "interpreter": "python",
        "log_path_policy": "Machine-specific absolute paths use portable placeholders; counts, exit codes, warnings and numerical results are retained.",
        "steps": rows,
        "software_checks_passed": not any(r["status"] == "failed" for r in rows),
        "full_browser_run_requested": not args.skip_browser,
        "extended_scientific_reference_passed": reference_passed,
        "configured_constant_pq_reference_passed": configured_reference_passed,
        "interpretation": "Expected scientific mismatches are explicit warnings, not passed validation. Skipped browser verification is not a complete release check.",
    }
    if (output / "backend-junit.xml").exists():
        report["backend_counts"] = junit_counts(output / "backend-junit.xml")
        junit = output / "backend-junit.xml"
        # Keep XML escaping valid when paths are represented by angle-bracket tokens.
        value = junit.read_text(encoding="utf-8")
        value = portable_text(value, ROOT, output)
        for token in ("project", "verification", "python-runtime"):
            value = value.replace("<" + token + ">", "&lt;" + token + "&gt;")
        junit.write_text(value, encoding="utf-8")
    if not args.skip_browser:
        browser_step = next(row for row in rows if row["name"] == "browser")
        try:
            path = output / "browser-results.json"
            report["browser_counts"] = browser_counts(path)
            path.write_text(
                portable_text(path.read_text(encoding="utf-8"), ROOT, output), encoding="utf-8"
            )
            counts = report["browser_counts"]
            if counts["passed"] == 0 or any(
                counts[k] for k in ("failed", "skipped", "errors", "flaky")
            ):
                raise ValueError("Browser cases failed, skipped, retried or did not complete")
        except (OSError, ValueError, KeyError, TypeError) as exc:
            browser_step["status"] = "failed"
            browser_step["error"] = "Structured browser verification failed: " + str(exc)
            report["software_checks_passed"] = False
    report["verified_inputs"] = inputs_before
    report["frontend_build"] = frontend_build(ROOT)
    if verification_inputs(ROOT) != inputs_before:
        report["software_checks_passed"] = False
        report["input_error"] = "Verification inputs changed while checks were running"
    (output / "verification.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2))
    return 0 if report["software_checks_passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
