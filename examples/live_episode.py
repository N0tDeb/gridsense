"""Run a native episode through the CLI and strictly replay its saved export."""

import json
import subprocess
import sys
from pathlib import Path
from tempfile import TemporaryDirectory

ROOT = Path(__file__).resolve().parents[1]


def main():
    with TemporaryDirectory(prefix="gridsense-episode-") as directory:
        output = Path(directory) / "episode.json"
        subprocess.run(
            [
                sys.executable,
                "-m",
                "gridsense.cli",
                "episode",
                "--config",
                str(ROOT / "examples/live_episode.json"),
                "--data-dir",
                directory,
                "--output",
                str(output),
            ],
            check=True,
            capture_output=True,
            text=True,
        )
        exported = json.loads(output.read_text(encoding="utf-8"))
        replay = subprocess.run(
            [sys.executable, "-m", "gridsense.cli", "replay-episode", "--file", str(output)],
            check=True,
            capture_output=True,
            text=True,
        )
        result = json.loads(replay.stdout)
        assert result["matched"] and result["ticks"] == 8
        frames = exported["frames"]
        assert frames[0]["electrical"]["unserved_kw"] < 0.001
        assert abs(frames[-1]["electrical"]["unserved_kw"] - 400) < 0.001
        assert not frames[-1]["physical"]["equipment_outages"]
        assert frames[-1]["physical"]["open_transformers"] == ["tx_a1"]
        print(
            json.dumps(
                {
                    "replay": result,
                    "initial_unserved_kw": frames[0]["electrical"]["unserved_kw"],
                    "final_unserved_kw": frames[-1]["electrical"]["unserved_kw"],
                    "repair_reconnected_transformer": False,
                },
                indent=2,
            )
        )


if __name__ == "__main__":
    main()
