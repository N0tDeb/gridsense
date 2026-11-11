"""Run voltage, derived-current/power and separately labelled balance checks."""

import argparse
import hashlib
import json
from importlib.resources import files
from pathlib import Path

from gridsense.reference_checks import validate_extended_reference
from gridsense.regression import harness_hash
from gridsense.service import utc_now

PROTOCOL = Path(__file__).resolve().parent / "protocols/electrical.json"
PROTOCOL_SHA256 = "7648402dcbfc3b61ff183d2448922ec437bc9c08c02e838ee4796b3334267774"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    if args.output and args.output.exists():
        parser.error("Output already exists; choose a new filename")
    data = PROTOCOL.read_bytes()
    if hashlib.sha256(data).hexdigest() != PROTOCOL_SHA256:
        parser.error("Frozen electrical-reference protocol changed")
    result = validate_extended_reference(json.loads(data))
    result.update(
        {
            "protocol_sha256": PROTOCOL_SHA256,
            "verified_at": utc_now(),
            "checker_sha256": hashlib.sha256(
                files("gridsense").joinpath("reference_checks.py").read_bytes()
            ).hexdigest(),
            "harness_sha256": harness_hash(),
            "source_pdf_sha256": "93efca4ca0f9da7f67ccfe14c8f94dabacf5b47e3d8a1b77a840802cbe5446a4",
        }
    )
    text = json.dumps(result, indent=2, allow_nan=False) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(text, encoding="utf-8")
    print(text)
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
