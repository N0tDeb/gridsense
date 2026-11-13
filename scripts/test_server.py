"""Disposable database for real browser tests; never touches user incidents."""

import argparse
from pathlib import Path
from tempfile import TemporaryDirectory
import uvicorn
from gridsense.api import create_app

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=8001)
    args = parser.parse_args()
    with TemporaryDirectory(prefix="gridsense-browser-") as data:
        app = create_app(data, Path(__file__).resolve().parents[1] / "frontend" / "dist")
        uvicorn.run(app, host="127.0.0.1", port=args.port, log_level="warning")
