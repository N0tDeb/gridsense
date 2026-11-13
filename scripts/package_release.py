"""Package verified source, resources and evidence; no environments or generated UI.

python scripts/package_release.py --output ../GridSense.zip
Checks the current verification, experiment fingerprints and runtime report.
The destination must not exist. This command does not publish to a remote repo.
"""

import argparse
import hashlib
import json
import zipfile
from datetime import datetime, timezone
from pathlib import Path

from gridsense import __version__
from gridsense.assurance import assurance_hash
from gridsense.failure_search import search_hash
from gridsense.regression import harness_hash
from gridsense.service import _differences, implementation_hash
from release_support import browser_counts, frontend_build, selected_files, verification_inputs

ROOT = Path(__file__).resolve().parents[1]


def digest(data):
    return hashlib.sha256(data).hexdigest()


def require(condition, message):
    if not condition:
        raise ValueError(message)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--verification-dir", type=Path, default=ROOT / "var/verification")
    parser.add_argument("--fresh-extraction-report", type=Path)
    args = parser.parse_args()
    destination = args.output.resolve()
    require(
        destination.suffix == ".zip" and not destination.exists(), "Use a new .zip output filename"
    )
    logs = args.verification_dir.resolve()
    verification = json.loads((logs / "verification.json").read_text(encoding="utf-8"))
    require(
        verification["software_checks_passed"] and verification["full_browser_run_requested"],
        "Complete software verification has not passed",
    )
    require(
        all(r["status"] in {"passed", "known-reference-mismatch"} for r in verification["steps"]),
        "A verification step failed or was skipped",
    )
    backend = verification["backend_counts"]
    require(
        backend["passed"] > 0 and all(backend[k] == 0 for k in ("failed", "skipped", "errors")),
        "Backend has failing/skipped/error tests",
    )
    browsers = browser_counts(logs / "browser-results.json")
    require(
        browsers["passed"] > 0
        and all(browsers[k] == 0 for k in ("failed", "skipped", "errors", "flaky"))
        and verification["browser_counts"] == browsers,
        "Browser suite is incomplete",
    )
    runtime = json.loads((logs / "runtime/runtime.json").read_text(encoding="utf-8"))
    require(runtime["health"]["version"] == __version__, "Runtime version differs from package")
    require(
        runtime["health_status"] == runtime["frontend_status"] == 200, "Runtime HTTP check failed"
    )
    require(
        not runtime["javascript_errors"] and not runtime["failed_requests"],
        "Runtime browser errors",
    )
    require(
        not any(r["overflow"] for r in runtime["viewport_checks"].values()),
        "Runtime horizontal overflow",
    )
    require(
        runtime["live_dashboard"].get("topology_connections") == 8
        and runtime["live_dashboard"].get("topology_labels_clear") is True,
        "Live topology connections and label placement were not verified",
    )
    require(
        all(
            runtime[k]["replay"]["matched"]
            for k in (
                "regression",
                "temporal",
                "search",
                "live_session",
                "controlled_session",
                "live_dashboard",
            )
        ),
        "Runtime replay failed",
    )
    campaign = json.loads(
        (ROOT / "experiments/assurance_results/results.json").read_text(encoding="utf-8")
    )
    session_study = json.loads(
        (ROOT / "experiments/session_results/results.json").read_text(encoding="utf-8")
    )
    from gridsense.episodes import episode_hash

    require(
        session_study["manifest"]["episode_sha256"] == episode_hash(),
        "Session study source changed",
    )
    require(
        any(
            r["name"] == "session-study-consistency" and r["status"] == "passed"
            for r in verification["steps"]
        ),
        "Session study consistency was not verified",
    )
    require(
        any(
            r["name"] == "session-challenge-consistency" and r["status"] == "passed"
            for r in verification["steps"]
        ),
        "Session challenge consistency was not verified",
    )
    require(
        any(
            r["name"] == "measurement-refresh-consistency" and r["status"] == "passed"
            for r in verification["steps"]
        ),
        "Measurement-refresh evidence was not verified",
    )
    require(
        any(
            r["name"] == "native-reuse-consistency" and r["status"] == "passed"
            for r in verification["steps"]
        ),
        "Native-reuse evidence was not verified",
    )
    require(
        any(
            r["name"] == "process-restart" and r["status"] == "passed"
            for r in verification["steps"]
        ),
        "Process restart was not verified",
    )
    require(campaign["manifest"]["assurance_sha256"] == assurance_hash(), "Campaign source changed")
    published = json.loads((logs / "voltage-reference.txt").read_text(encoding="utf-8"))
    json.dumps(published, allow_nan=False)
    require(
        published["configuration"] == "ieee13-published-official-reference-v2"
        and published["passed"] is True
        and published["converged"] is True
        and len(published["rows"]) == 29
        and all(row["passed"] is True for row in published["rows"])
        and published["reference_sha256"]
        == digest((ROOT / "backend/gridsense/references/ieee13_published_v2.json").read_bytes())
        and published["model_sha256"]
        == digest((ROOT / "backend/gridsense/circuits/ieee13/model.dss").read_bytes()),
        "Corrected published reference failed or its inputs changed",
    )
    reference = json.loads((logs / "electrical-reference.json").read_text(encoding="utf-8"))
    require(
        reference["checker_sha256"]
        == digest((ROOT / "backend/gridsense/reference_checks.py").read_bytes()),
        "Reference checker source changed",
    )
    configured = json.loads((logs / "configured-reference.json").read_text(encoding="utf-8"))
    saved_configured = json.loads(
        (ROOT / "experiments/configured_reference_results/results.json").read_text(encoding="utf-8")
    )
    json.dumps(configured, allow_nan=False)
    require(
        not _differences(
            {key: value for key, value in configured.items() if key != "verified_at"},
            {key: value for key, value in saved_configured.items() if key != "verified_at"},
            "configured_reference",
            1e-7,
        ),
        "Configured reference differs from the signed, freshly verified report",
    )
    require(
        verification.get("configured_constant_pq_reference_passed") is True
        and any(
            row["name"] == "configured-pq-reference" and row["status"] == "passed"
            for row in verification["steps"]
        )
        and configured["configuration"] == "ieee13-constant-pq-reference-v1"
        and configured["passed"] is True
        and configured["passed_checks"] == configured["total_checks"] == 56
        and len(configured["checks"]) == 56
        and all(row["passed"] is True for row in configured["checks"])
        and configured["native_default_baseline_matched"] is True
        and configured["inputs_sha256"]
        and all(
            digest((ROOT / name).read_bytes()) == fingerprint
            for name, fingerprint in configured["inputs_sha256"].items()
        ),
        "Configured constant-PQ reference failed or its inputs changed",
    )
    model_reference = json.loads((logs / "model-reference.json").read_text(encoding="utf-8"))
    require(
        model_reference["passed"]
        and model_reference["selected_convergence_passed"]
        and model_reference["protocol_sha256"]
        == digest((ROOT / "experiments/protocols/model_reference.json").read_bytes())
        and model_reference["checker_sha256"]
        == digest((ROOT / "backend/gridsense/model_reference.py").read_bytes())
        and model_reference["runner_sha256"]
        == digest((ROOT / "experiments/run_model_reference.py").read_bytes()),
        "Model-aware reference failed or source/protocol changed",
    )
    require(
        verification.get("verified_inputs") == verification_inputs(ROOT),
        "Source/configuration differs from the verified inputs; run verification again",
    )
    require(
        runtime.get("verified_inputs") == verification_inputs(ROOT),
        "Runtime report does not match current source/configuration",
    )
    require(
        verification.get("frontend_build") == frontend_build(ROOT),
        "Built frontend differs from the verified build",
    )
    fresh = {"status": "not_performed"}
    if args.fresh_extraction_report:
        fresh = json.loads(args.fresh_extraction_report.read_text(encoding="utf-8"))
        require(
            fresh.get("passed") is True
            and fresh.get("verified_inputs") == verification_inputs(ROOT),
            "Fresh-extraction evidence does not match the tested source",
        )
    summary = {
        "schema_version": 1,
        "verified_at": verification["verified_at"],
        "platform": verification["platform"],
        "python": verification["python"],
        "software_checks_passed": verification["software_checks_passed"],
        "backend_counts": backend,
        "browser_counts": browsers,
        "steps": [
            {k: row[k] for k in ("name", "status", "exit_code", "expected_exit") if k in row}
            for row in verification["steps"]
        ],
        "verified_inputs": verification["verified_inputs"],
        "frontend_build": verification["frontend_build"],
        "runtime": {
            "health_status": runtime["health_status"],
            "frontend_status": runtime["frontend_status"],
            "strict_replay_flows": {
                key: runtime[key]["replay"]["matched"]
                for key in (
                    "regression",
                    "temporal",
                    "search",
                    "live_session",
                    "controlled_session",
                    "live_dashboard",
                )
            },
            "viewport_checks": runtime["viewport_checks"],
            "topology_labels_clear": runtime["live_dashboard"]["topology_labels_clear"],
            "javascript_errors": runtime["javascript_errors"],
            "failed_requests": runtime["failed_requests"],
        },
        "restart": json.loads((logs / "restart/restart.json").read_text(encoding="utf-8")),
        "references": {
            "public_voltage_passed": published["passed"],
            "public_voltage_count": len(published["rows"]),
            "constant_power_passed": configured["passed"],
            "constant_power_passed_checks": configured["passed_checks"],
            "native_default_passed_checks": configured["native_default_baseline"]["passed_checks"],
            "model_aware_passed": model_reference["passed"],
        },
        "fresh_extraction": fresh,
        "unverified": [
            "Windows execution",
            "GitHub-hosted CI",
            "independent human software and power-systems reviews",
        ],
        "scope": "Actual local software/native verification and retained study consistency. No claim of field validation or a rerun of every stored campaign.",
    }
    summary_path = ROOT / "docs/verification/summary.json"
    summary_path.parent.mkdir(parents=True, exist_ok=True)
    summary_path.write_text(json.dumps(summary, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    paths = sorted(selected_files(ROOT))
    hashes = {p.relative_to(ROOT).as_posix(): digest(p.read_bytes()) for p in paths}
    require(
        all(
            name in hashes
            for name in (
                "README.md",
                "SETUP.md",
                "scripts/verify.py",
                "frontend/src/App.tsx",
                "docs/verification/summary.json",
            )
        ),
        "Missing source/setup/verification artifact",
    )
    manifest = {
        "project": "GridSense — Live Grid Restoration and Controller Testing",
        "version": __version__,
        "packaged_at": datetime.now(timezone.utc).isoformat(),
        "start_here": "README.md",
        "setup": "SETUP.md",
        "verification": "docs/VERIFICATION.md",
        "assurance": "docs/ASSURANCE.md",
        "walkthrough": "docs/WALKTHROUGH.md",
        "status": "Linux software/runtime verified; corrected Official-column reference 29/29; constant-PQ v1 56/56; native-default legacy 52/56 retained; Windows/hosted CI/human review pending",
        "tests": {"backend": backend, "browser": browsers},
        "core_sha256": implementation_hash(),
        "search_sha256": search_hash(),
        "harness_sha256": harness_hash(),
        "assurance_sha256": assurance_hash(),
        "campaign_costs": campaign["costs"],
        "campaign_pairs": len(campaign["rows"]),
        "session_comparison": {
            "episodes": len(session_study["rows"]),
            "sequence_reference_matches": sum(r["matched"] for r in session_study["references"]),
            "dense_plan_checks": len(session_study["dense_checks"]),
            "costs": session_study["costs"],
        },
        "temporal_episodes": len(campaign["temporal_rows"]),
        "defect_reproducer_pairs": len(campaign["reproducers"]),
        "published_official_reference": {
            "configuration": published["configuration"],
            "passed": published["passed"],
            "passed_checks": sum(row["passed"] for row in published["rows"]),
            "total_checks": len(published["rows"]),
            "reference_sha256": published["reference_sha256"],
            "corrections": published["corrections"],
        },
        "extended_reference": {
            "passed": reference["passed"],
            "voltage_passed": reference["published_voltage"]["passed"],
            "failing_checks": [r["id"] for r in reference["additional_checks"] if not r["passed"]],
        },
        "configured_constant_pq_reference": {
            "configuration": configured["configuration"],
            "passed": configured["passed"],
            "passed_checks": configured["passed_checks"],
            "total_checks": configured["total_checks"],
            "profile_sha256": configured["inputs_sha256"][
                "experiments/protocols/constant_pq_reference_v1.json"
            ],
            "original_native_default_passed_checks": configured["native_default_baseline"][
                "passed_checks"
            ],
        },
        "model_aware_reference": {
            "configuration": model_reference["configuration"],
            "passed": model_reference["passed"],
            "categories": {
                key: {
                    "passed": sum(r["passed"] for r in model_reference[key]),
                    "total": len(model_reference[key]),
                }
                for key in (
                    "published_voltage_checks",
                    "declared_model_checks",
                    "model_envelope_checks",
                    "internal_balance_checks",
                )
            },
            "scope": model_reference["scope"],
        },
        "reviews": json.loads((ROOT / "docs/reviews/STATUS.json").read_text(encoding="utf-8")),
        "exclusions": [
            "built frontend (recreated by documented build)",
            "raw verification logs and browser captures",
            "virtual environments",
            "node_modules",
            "runtime SQLite data",
            "browser binaries",
            "caches",
        ],
        "hash_note": "All archive files except this manifest are listed. Paths are relative to gridsense/.",
        "files": [
            {
                "path": p.relative_to(ROOT).as_posix(),
                "sha256": hashes[p.relative_to(ROOT).as_posix()],
                "bytes": p.stat().st_size,
            }
            for p in paths
        ],
    }
    manifest_text = json.dumps(manifest, indent=2, allow_nan=False) + "\n"
    (ROOT / "RELEASE_MANIFEST.json").write_text(manifest_text, encoding="utf-8")
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_suffix(".zip.tmp")
    require(not temporary.exists(), "Temporary archive already exists; choose a new destination")
    with zipfile.ZipFile(
        temporary, "x", compression=zipfile.ZIP_DEFLATED, compresslevel=9
    ) as archive:
        for path in paths:
            archive.write(path, "gridsense/" + path.relative_to(ROOT).as_posix())
        archive.writestr("gridsense/RELEASE_MANIFEST.json", manifest_text)
    with zipfile.ZipFile(temporary) as archive:
        require(archive.testzip() is None, "ZIP CRC verification failed")
        require(len(archive.namelist()) == len(paths) + 1, "Unexpected archive entry count")
        for item in manifest["files"]:
            require(
                digest(archive.read("gridsense/" + item["path"])) == item["sha256"],
                "Archive content hash mismatch",
            )
    temporary.replace(destination)
    print(
        json.dumps(
            {
                "file": str(destination),
                "bytes": destination.stat().st_size,
                "entries": len(paths) + 1,
                "sha256": digest(destination.read_bytes()),
                "tests": manifest["tests"],
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
