# Contributing to GridSense

Use [SETUP.md](SETUP.md) for installation and [DEVELOPMENT.md](DEVELOPMENT.md)
for the source and evidence workflow. The dashboard and CLI share the same
native simulation implementation.

## Report an issue

Include the application version, operating system, Python and Node versions,
steps to reproduce, expected behavior and actual behavior. A minimal scenario
or session export helps reproduce a simulation issue. Remove private local
paths and other sensitive information from logs and exports before attaching
them. Follow [SECURITY.md](SECURITY.md) for security reports.

## Prepare a change

Explain the behavior being changed and add a regression when the change fixes
a behavior defect. Run these checks from the project directory:

```bash
python -m ruff check backend scripts examples
python -m ruff format --check backend scripts examples experiments
python scripts/verify.py --output-dir var/contribution-check
```

The verification command requires the frontend dependencies and a compatible
Playwright Chromium installation described in SETUP.md. From `frontend/`, also
run `npm audit --audit-level=high` when changing dependencies.

Simulation source bytes are part of replay identity. Refresh the affected
experiment evidence by executing its protocol after a relevant implementation
change; do not replace hashes in historical outcomes. Keep known reference
mismatches and unsuccessful trials visible. In a pull request, describe the
change, relevant checks and the evidence that was refreshed.

## Project license

GridSense's original source and original documentation are licensed under the
[Apache License 2.0](LICENSE). Copyright 2026
[N0tDeb](https://github.com/N0tDeb); see [NOTICE](NOTICE) for attribution.
Contributions intentionally submitted for inclusion are provided under Apache
2.0 unless explicitly stated otherwise or covered by a separate agreement.
Bundled third-party components retain their respective licenses and notices.
