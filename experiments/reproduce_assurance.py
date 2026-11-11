"""Reproduce a retained controller mutation without a database or web server."""

import argparse
import json
from pathlib import Path

from gridsense.assurance import replay_defect


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("file", type=Path)
    args = parser.parse_args()
    try:
        value = json.loads(args.file.read_text(encoding="utf-8-sig"))
        if not isinstance(value, dict):
            raise ValueError("Expected a JSON object")
        result = replay_defect(value)
    except (OSError, ValueError, KeyError, TypeError) as exc:
        parser.exit(2, f"Invalid or incompatible reproducer: {exc}\n")
    print(json.dumps(result, indent=2, allow_nan=False))
    return 0 if result["matched"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
