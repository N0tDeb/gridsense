# Development

Follow [SETUP.md](SETUP.md), then read the [architecture](docs/ARCHITECTURE.md),
[engineering contracts](docs/ENGINEERING_CONTRACTS.md) and
[walkthrough](docs/WALKTHROUGH.md). The authoritative application is under
`backend/gridsense/` and `frontend/src/`.

## Quality checks

```bash
python -m ruff check backend scripts examples
python -m ruff format --check backend scripts examples experiments
python scripts/check_repository.py
python scripts/verify.py --output-dir var/verification
```

From `frontend/`, run `npm run format:check` and `npm audit --audit-level=high`.
Use `python -m ruff format ...` and `npm run format` to apply formatting.
Python formatting uses pinned Ruff; frontend formatting uses pinned Prettier.
Do not reformat fingerprinted simulation files without refreshing affected evidence.

The complete verifier builds the frontend, uses a real native backend and
Chromium, checks the stored study denominators/source identities and replays the
portable examples. It records failed, skipped and flaky tests explicitly.
`--campaign` also executes the complete fault-injection matrix in a new directory.

## Source identity and evidence

Strict replay hashes exact source/model bytes and identifies the native solver.
Formatting can therefore change compatibility. Saved inputs remain useful for a
new current-code evaluation, which records its own identity and baseline.
Foreign-build fixtures test refusal of incompatible records; they are not examples
to run as current records.

The current study results live beside their protocols in `experiments/`.
Fingerprint checks verify integrity and accounting; they do not substitute for
executing a changed algorithm. If relevant simulation source changes, actually
rerun the affected protocol and inspect favorable and unfavorable results before
replacing any bundled study. Never edit hashes in outcomes to claim compatibility.

The discovery study contains frozen source fixtures for its trace/accounting
checker. They are study inputs, not another application implementation, and must
not replace active modules. [Experiment guide](experiments/README.md).

## Architecture boundaries

The frontend displays backend results and submits commands. The backend owns
simulation time, electrical calculations, decisions and transactions. Controllers
receive delivered observations, not evaluator truth or future events. New trusted
selectors use the documented interface; do not accept arbitrary code or DSS text
from HTTP clients. See [controller testing](docs/CONTROLLER_TESTING.md).

Use a regression when fixing a behavior defect. Preserve actual failed inputs,
request receipts and record identity. Scope additional tests to the relevant
contract. Update documentation when observable behavior changes.

## Release packaging

After complete verification, from the project root:

```bash
python scripts/package_release.py --verification-dir var/verification --output ../GridSense.zip
```

The packager requires passing structured backend/browser results, fresh native
references, current input/build fingerprints, runtime/restart checks and consistent
study data. It creates one `gridsense/` root and checks every file hash and ZIP CRC.
The source package excludes `.git`, virtual environments, installed dependencies,
built frontend, runtime databases, caches, browser captures and verification logs.
The source build is documented in SETUP.md. LICENSE, NOTICE, circuit data and
third-party notices are retained.

The release command generates `RELEASE_MANIFEST.json` and
`docs/verification/summary.json` for the source and verification logs supplied
at packaging time. Do not treat a previously generated report as evidence for a
newer commit. Raw run logs remain in ignored `var/`; hosted execution results
are retained as GitHub Actions artifacts.

Extract the result separately, create a fresh environment, follow SETUP.md and
check startup/native workflows. A source/hash equality check complements, but
does not replace, actual installation and application execution.

## Result visualization

The [session figure](docs/figures/session-outcomes.svg) is generated directly from
`experiments/session_results/results.json`. To regenerate it, install the optional
plotting extra (not needed to run or test the app):

```bash
python -m pip install -e '.[plots]'
python scripts/plot_results.py
```

Matplotlib is pinned in that extra. The SVG uses editable text and is viewable
on GitHub without Python. No measurements are inferred or synthesized.
