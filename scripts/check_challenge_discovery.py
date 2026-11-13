"""Verify the retained discovery run against its archived controller and runner.

This is source/trace/accounting verification, not strict replay under the current
controller. Complete original dependency bytes are checked against its freeze.
"""

import hashlib
import importlib
import importlib.machinery
import importlib.util
import json
import sys
from contextlib import contextmanager
from pathlib import Path
from tempfile import TemporaryDirectory

ROOT = Path(__file__).resolve().parents[1]
ARCHIVE = ROOT / "experiments/challenge_discovery"


def discovery_episode_hash():
    # Same named-byte framing as episodes.episode_hash; source is immutable
    # discovery evidence, independent of the current implementation.
    names = (
        "domain.py",
        "electrical.py",
        "network.py",
        "episodes.py",
        "telemetry.py",
        "rules.py",
        "control.py",
        "restoration.py",
        "switching.py",
        "episode_metrics.py",
        "session_store.py",
        "session_api.py",
        "service.py",
    )
    return hashlib.sha256(
        b"".join(
            name.encode() + (ARCHIVE / "source" / (name + ".txt")).read_bytes() for name in names
        )
    ).hexdigest()


def load_archived_module(name, path):
    loader = importlib.machinery.SourceFileLoader(name, str(path))
    spec = importlib.util.spec_from_loader(loader.name, loader)
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module


@contextmanager
def archived_episode_config():
    """Use the original input schema, without new current-code defaults."""
    name = "_gridsense_discovery_parser"
    with TemporaryDirectory(prefix="gridsense-discovery-parser-") as directory:
        root = Path(directory)
        for source in (ARCHIVE / "source").glob("*.py.txt"):
            (root / source.name.removesuffix(".txt")).write_bytes(source.read_bytes())
        entry = root / "__init__.py"
        entry.write_text("", encoding="utf-8")
        spec = importlib.util.spec_from_file_location(
            name, entry, submodule_search_locations=[str(root)]
        )
        package = importlib.util.module_from_spec(spec)
        sys.modules[name] = package
        try:
            spec.loader.exec_module(package)
            yield importlib.import_module(name + ".episodes").EpisodeConfig
        finally:
            for key in tuple(sys.modules):
                if key == name or key.startswith(name + "."):
                    sys.modules.pop(key)


def verify_discovery():
    freeze = json.loads((ARCHIVE / "freeze.json").read_text(encoding="utf-8"))
    helper_path = ARCHIVE / "source/run_session_benchmark.py.txt"
    runner_path = ARCHIVE / "runner.py.txt"
    for path, key in (
        (helper_path, "outcome_helper_sha256"),
        (runner_path, "runner_sha256"),
    ):
        if hashlib.sha256(path.read_bytes()).hexdigest() != freeze["fingerprints"][key]:
            raise ValueError("Archived report source differs from frozen discovery source")
    if discovery_episode_hash() != freeze["fingerprints"]["episode_sha256"]:
        raise ValueError("Archived episode source differs from frozen discovery source")
    helper = load_archived_module("discovery_outcome_helper", helper_path)
    previous_helper = sys.modules.get("run_session_benchmark")
    sys.modules["run_session_benchmark"] = helper
    try:
        module = load_archived_module("discovery_runner", runner_path)
    finally:
        if previous_helper is None:
            sys.modules.pop("run_session_benchmark", None)
        else:
            sys.modules["run_session_benchmark"] = previous_helper
    original_file_hash = module.file_hash
    current_helper_path = ROOT / "experiments/run_session_benchmark.py"

    def archived_file_hash(path):
        # Resolve the frozen runner's helper dependency to its retained bytes.
        # Original freeze, outcomes and fingerprint fields remain unchanged.
        return original_file_hash(helper_path if Path(path) == current_helper_path else path)

    module.file_hash = archived_file_hash
    module.ROOT = ROOT
    module.PROTOCOL = ARCHIVE / "protocol.json"
    module.FREEZE = ARCHIVE / "freeze.json"
    module.episode_hash = discovery_episode_hash
    with archived_episode_config() as config:
        module.EpisodeConfig = config
        result = module.verify_report(ARCHIVE)
    return {
        **result,
        "kind": "retained_discovery_accounting",
        "current_controller_replay": False,
    }


def main():
    print(
        json.dumps(
            verify_discovery(),
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
