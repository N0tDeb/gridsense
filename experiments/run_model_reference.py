"""Run the named model-aware reference without changing the native load envelope."""

import argparse
import hashlib
import json
from pathlib import Path
from importlib.resources import files

from gridsense.model_reference import validate_model_reference
from gridsense.service import utc_now

ROOT = Path(__file__).resolve().parent
PROTOCOL_SHA256 = "a49079a4db4d819c48bd8807357c92a53fd3cb57eb3f1487fa7dd4f2a6eadeb5"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        parser.error("Output exists; choose a new filename")
    data = (ROOT / "protocols/model_reference.json").read_bytes()
    if hashlib.sha256(data).hexdigest() != PROTOCOL_SHA256:
        parser.error("Named model-reference protocol changed; review its configuration")
    protocol = json.loads(data)
    published = (ROOT / "protocols/electrical.json").read_bytes()
    if hashlib.sha256(published).hexdigest() != protocol["published_inputs_protocol_sha256"]:
        parser.error("Published reference inputs changed")
    result = validate_model_reference(protocol, json.loads(published))
    result.update(
        {
            "verified_at": utc_now(),
            "protocol_sha256": hashlib.sha256(data).hexdigest(),
            "checker_sha256": hashlib.sha256(
                files("gridsense").joinpath("model_reference.py").read_bytes()
            ).hexdigest(),
            "runner_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        }
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    for category in (
        "published_voltage_checks",
        "declared_model_checks",
        "model_envelope_checks",
        "internal_balance_checks",
    ):
        rows = result[category]
        print(f"{category}: {sum(r['passed'] for r in rows)}/{len(rows)}")
    print("Selected convergence:", result["selected_convergence_passed"])
    print("Scope:", result["scope"])
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
