"""Check real CLI startup, persisted commands, restart and replay over HTTP.

Uses a disposable data path containing spaces and Unicode. Run from an installed
source checkout with the frontend built; no existing application data is opened.
"""

import argparse
import json
import os
import platform
import socket
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[1]


def check(output):
    if output.exists() and any(output.iterdir()):
        raise ValueError("Use a new empty output directory")
    output.mkdir(parents=True, exist_ok=True)
    with socket.socket() as reservation:
        reservation.bind(("127.0.0.1", 0))
        port = reservation.getsockname()[1]
    base = f"http://127.0.0.1:{port}"
    process, log = None, None
    health, frontend = [], []
    with tempfile.TemporaryDirectory(prefix="gridsense spaces Δ ") as data_dir:
        with httpx.Client(base_url=base, timeout=90, trust_env=False) as client:

            def request(method, path, **kwargs):
                response = client.request(method, path, **kwargs)
                response.raise_for_status()
                return response.json()

            def launch(number):
                nonlocal process, log
                log = (output / f"server-{number}.txt").open("w", encoding="utf-8")
                process = subprocess.Popen(
                    [
                        sys.executable,
                        "-m",
                        "gridsense.cli",
                        "serve",
                        "--port",
                        str(port),
                        "--data-dir",
                        data_dir,
                    ],
                    cwd=ROOT,
                    env={**os.environ, "PYTHONUTF8": "1"},
                    stdout=log,
                    stderr=subprocess.STDOUT,
                )
                deadline = time.monotonic() + 30
                while time.monotonic() < deadline:
                    if process.poll() is not None:
                        raise RuntimeError(
                            f"Server exited during startup; inspect server-{number}.txt"
                        )
                    try:
                        response = client.get("/api/health", timeout=1)
                        if response.status_code == 200:
                            health.append(response.json())
                            response = client.get("/")
                            response.raise_for_status()
                            if 'id="root"' not in response.text:
                                raise ValueError("Built frontend document missing")
                            frontend.append(response.status_code)
                            return
                    except httpx.TransportError:
                        pass
                    time.sleep(0.1)
                raise RuntimeError("Server readiness timed out")

            def stop(*, abrupt=False):
                nonlocal process, log
                if process is not None:
                    if process.poll() is None:
                        process.kill() if abrupt else process.terminate()
                    try:
                        process.wait(timeout=15)
                    except subprocess.TimeoutExpired:
                        process.kill()
                        process.wait(timeout=5)
                    process = None
                if log is not None:
                    log.close()
                    log = None

            try:
                launch(1)
                receipt = request(
                    "POST",
                    "/api/sessions",
                    json={
                        "request_id": "restart-create",
                        "config": {
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
                        },
                    },
                )
                path = "/api/sessions/" + receipt["id"]
                action = {"request_id": "restart-step", "expected_revision": 0, "operation": "step"}
                receipt = request("POST", path + "/actions", json=action)
                before = request("GET", path + "/export")
                commands = before["final"]["checkpoint"]["control"]["commands"]
                if len(commands) != 1 or next(iter(commands.values()))["status"] != "pending":
                    raise ValueError("Expected a persisted pending command before termination")
                stop(abrupt=True)
                launch(2)
                state = request("GET", path)
                if state["mode"] != "paused" or state["at_s"] != 1:
                    raise ValueError("Restart advanced the clock or resumed playback")
                if request("GET", path + "/export") != before:
                    raise ValueError("Restart changed the committed paused session")
                if request("POST", path + "/actions", json=action) != receipt:
                    raise ValueError("Retry did not return the original committed receipt")
                if request("GET", path + "/export") != before:
                    raise ValueError("Retry duplicated a committed action")
                while receipt["at_s"] < 8:
                    receipt = request(
                        "POST",
                        path + "/actions",
                        json={
                            "request_id": f"resume-{receipt['at_s']}",
                            "expected_revision": receipt["revision"],
                            "operation": "step",
                        },
                    )
                record = request("GET", path + "/export")
                replay = request("POST", path + "/replay")
                final = record["frames"][-1]
                if not replay["matched"] or final["electrical"]["unserved_kw"] > 0.1:
                    raise ValueError("Recovered session failed native restoration or strict replay")
                if len(final["control"]["commands"]) != 3 or any(
                    c["status"] != "confirmed" for c in final["control"]["commands"].values()
                ):
                    raise ValueError("Command lifecycle incomplete after restart")
                (output / "episode.json").write_text(
                    json.dumps(record, indent=2) + "\n", encoding="utf-8"
                )
                report = {
                    "passed": True,
                    "platform": platform.platform(),
                    "python": platform.python_version(),
                    "health": health,
                    "frontend_status": frontend,
                    "data_path_spaces_and_unicode": True,
                    "abrupt_server_restart": True,
                    "pending_command_preserved": True,
                    "idempotent_retry": True,
                    "ticks": 8,
                    "confirmed_commands": 3,
                    "replay": replay,
                }
                (output / "restart.json").write_text(
                    json.dumps(report, indent=2) + "\n", encoding="utf-8"
                )
                return report
            finally:
                stop()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(check(args.output_dir.resolve()), indent=2))


if __name__ == "__main__":
    main()
