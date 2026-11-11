"""Exercise confirmed restoration and a missing-confirmation case through the CLI."""

import json
import subprocess
import sys
from pathlib import Path
from tempfile import TemporaryDirectory

ROOT = Path(__file__).resolve().parents[1]


def main():
    reports = []
    base = json.loads((ROOT / "examples/restoration_episode.json").read_text(encoding="utf-8"))
    with TemporaryDirectory(prefix="gridsense-restoration-") as directory:
        for name in ("confirmed", "missing-confirmation"):
            config = json.loads(json.dumps(base))
            if name == "missing-confirmation":
                config["control"]["confirmation_timeout_s"] = 2
                config["events"].append(
                    {
                        "kind": "actuator",
                        "at_s": 1,
                        "equipment": "line:tie_c",
                        "drop_feedback": True,
                    }
                )
            definition, output = (
                Path(directory) / (name + "-input.json"),
                Path(directory) / (name + ".json"),
            )
            definition.write_text(json.dumps(config), encoding="utf-8")
            subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "gridsense.cli",
                    "episode",
                    "--config",
                    str(definition),
                    "--data-dir",
                    directory,
                    "--output",
                    str(output),
                ],
                check=True,
                capture_output=True,
                text=True,
                timeout=120,
            )
            record = json.loads(output.read_text(encoding="utf-8"))
            replay = subprocess.run(
                [sys.executable, "-m", "gridsense.cli", "replay-episode", "--file", str(output)],
                check=True,
                capture_output=True,
                text=True,
                timeout=120,
            )
            result = json.loads(replay.stdout)
            assert result["matched"]
            control = record["frames"][-1]["control"]
            commands = list(control["commands"].values())
            if name == "confirmed":
                assert len(commands) == 3 and all(c["status"] == "confirmed" for c in commands)
                assert control["supply_status"] == "normal_supply_verified"
                assert record["frames"][6]["electrical"]["unserved_kw"] > 999
            else:
                assert len(commands) == 1 and commands[0]["status"] == "unknown"
                assert record["frames"][3]["control"]["status"] == "confirmation_unknown"
                assert control["supply_status"] == "alternate_supply_verified"
            reports.append(
                {
                    "case": name,
                    "replay": result,
                    "commands": len(commands),
                    "supply": control["supply_status"],
                    "metrics": record["frames"][-1]["metrics"],
                }
            )
    print(json.dumps(reports, indent=2))


if __name__ == "__main__":
    main()
