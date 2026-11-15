# Setup

## Requirements

Use Python **3.12** and Node **24** to reproduce the verification environment.
The pinned Python dependencies require Python 3.12+; the frontend requires Node
22.12+. A CPU machine is sufficient. Installation needs internet access.
The app needs no account, API key, GPU, external database or downloaded ML model.

Run commands from the extracted `gridsense/` directory. The ZIP contains source,
locked dependency definitions and bundled circuit data. It intentionally omits
installed dependencies, the built dashboard, runtime databases and browser binaries.

## Linux and macOS

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements-dev.lock
python -m pip install -e . --no-deps
cd frontend
npm ci
npm run build
cd ..
python -m gridsense.cli serve
```

Open **http://127.0.0.1:8000**. The editable installation makes the source tree,
bundled model data and built `frontend/dist/` available to the application.
Keep this project directory while using the installation. A bare Python wheel
is a backend package; it does not contain the React dashboard.

## Windows PowerShell

Python activation and execution-policy changes are unnecessary:

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.lock
.\.venv\Scripts\python.exe -m pip install -e . --no-deps
Set-Location frontend
npm.cmd ci
npm.cmd run build
Set-Location ..
.\.venv\Scripts\python.exe -m gridsense.cli serve
```

These are supported setup instructions, with execution status recorded in
[verification](docs/VERIFICATION.md). Do not infer Windows verification from the
presence of its CI configuration.

## Database and configuration

Startup creates `var/gridsense.sqlite3` and the required tables automatically.
There is no separate database server, migration command or seed-data import.
The dashboard can create its first session immediately. Bundled examples and
study results are separate from the runtime database.

No `.env` file is required or automatically loaded. Optional settings are:

| Setting | Use |
| --- | --- |
| `--data-dir PATH` | CLI data directory; default `var/` relative to the current directory |
| `--port NUMBER` | CLI server port; default 8000 |
| `GRIDSENSE_DATA_DIR` | Data directory when launching the ASGI app directly with Uvicorn |
| `GRIDSENSE_PYTHON` | Absolute Python executable for browser tests when it is not on PATH |
| `PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH` | Optional compatible installed Chromium for tests |
| `PLAYWRIGHT_CHROMIUM_ARGS` | Optional JSON array of Chromium launch arguments for a constrained test environment |
| `GRIDSENSE_BROWSER_REPORT` | Optional Playwright JSON report path; the full verifier supplies it |

For example:

```bash
python -m gridsense.cli serve --data-dir /path/to/data --port 8002
```

The CLI supplies its `--data-dir` value to the server. Use that flag when starting
through the CLI. Keep the one-process local server on loopback: authentication,
TLS and multiuser access control are outside this application's scope.

SQLite uses WAL transactions. Back up a running database with SQLite's backup
API or stop the server before copying it. Copying only the main file while it
is running can omit committed WAL data. Never commit runtime databases or exports
containing private information.

On POSIX systems, use a native UTF-8 locale when the project, virtual environment
or working directory contains non-ASCII characters. Python 3.12 editable/native
imports can fail before application startup under forced ASCII filesystem decoding;
the bundled DSS backend also requires a UTF-8 locale for a Unicode working directory.
Use an installed locale such as `LC_ALL=C.UTF-8`, or an ASCII-only directory.
`PYTHONUTF8=1` alone does not configure the native library's locale.

## Development server

With the Python environment active, use two terminals:

```bash
python -m uvicorn gridsense.api:app --reload --host 127.0.0.1 --port 8000
```

```bash
cd frontend
npm run dev
```

Open Vite's printed URL, normally http://127.0.0.1:5173. Its development proxy
forwards `/api` to port 8000. The production build uses one FastAPI origin.

## Verify the installation

A successful startup performs a real OpenDSS solve. `/api/health` reports native
readiness and `/docs` exposes interactive API documentation. A broken simulation
worker pool returns HTTP 503 and requires a server restart; queue congestion does
not falsely mark it broken.

Install the browser used by the UI tests, from `frontend/`:

```bash
npx playwright install chromium
```

On Linux, if system browser libraries are missing, use Playwright's documented
`npx playwright install --with-deps chromium` with permission to install OS packages.
No browser is required for ordinary backend/CLI operation.

From the project root, with its Python environment active:

```bash
python -m pip check
python -m pytest backend/tests/ -q
python scripts/verify.py --output-dir var/verification
```

The complete verifier checks source/documentation integrity, formatting, backend
and browser tests, references, study consistency, portable replay, startup, mobile
geometry and abrupt restart recovery. It creates a new report directory and
refuses nonempty destinations. Browser tests use a disposable database and port
8001, which must be free. Install frontend dependencies before running them.
`--skip-browser` records an incomplete run and cannot qualify a release.

PowerShell can run the same commands with `.\.venv\Scripts\python.exe`.
The verifier selects that interpreter for its browser backend automatically.

## Headless workflows

With the environment active, `python -m gridsense.cli` and `gridsense` are
interchangeable. Use fresh output paths:

```bash
gridsense demo --output var/incident.json
gridsense sweep --output var/sweep.json
gridsense search --seed 42 --budget 24 --output var/search.json
gridsense reproduce --file var/search.json
gridsense regress --output var/regression.json
gridsense verify-run --file var/regression.json
gridsense temporal --seed 42 --budget 4 --output var/temporal.json
gridsense episode --config examples/restoration_episode.json --output var/episode.json
gridsense replay-episode --file var/episode.json
gridsense validate-feeder --output var/voltage-reference.json
```

`replay --incident ID` reads a saved incident from its data directory. Portable
search/controller/episode exports replay without the original database. Strict
replay requires matching source, model, native solver and record integrity.
Current-code regression is a separate operation that creates a new evaluation.

[Evaluation](docs/EVALUATION.md) lists the reproducible studies.
[Reference validation](docs/REFERENCE_VALIDATION.md) explains why the declared
constant-power comparison passes 56/56 while the native-default audit records
52/56. The latter intentionally exits 1 and is not an installation failure.

## Troubleshooting

| Symptom | Action |
| --- | --- |
| Missing Python module or `gridsense` command | Use this project's virtual environment and run both Python installation commands |
| API works but `/` returns 404 | Run `npm ci` and `npm run build` in `frontend/`, then restart the server |
| Browser cannot reach the backend | Check the Python server and Vite proxy port; keep normal serving on one origin |
| Readiness returns 503 | Inspect the local server output and restart the broken simulation pool |
| Browser download or launch fails | Install Chromium and required OS libraries, or explicitly select a compatible installed browser |
| Strict replay reports a mismatch | Inspect source/solver identities and record integrity; do not bypass the check |
| Fresh telemetry is rejected | With zero age, reported west demand must equal actual west demand |
| Native import fails in a Unicode path | Check the POSIX native locale, or use an ASCII path |
| Port 8000 is occupied | Select `--port 8002`; adjust the Vite proxy when using development mode |

See [API](docs/API.md), [architecture](docs/ARCHITECTURE.md),
[workflow walkthrough](docs/WALKTHROUGH.md) and [security](SECURITY.md).
