# Repository and release

The `gridsense/` directory is the repository root. It contains the complete
application, locked dependencies, tests, model data, license notices, documentation
and reproducible studies. It needs no preceding ZIP, patch or external project folder.

## Source and generated files

Commit source, lockfiles, required assets, tests and frozen study inputs.
Generate release manifests and verification summaries from the exact verified
source rather than retaining generated reports that become stale after changes.
The application builds the dashboard into `frontend/dist/`; regenerate it with
`npm ci` and `npm run build`. Do not commit environments, `node_modules`, local
browser binaries, runtime databases, secret configuration or test captures.
`.gitignore` and the source ZIP packager enforce these boundaries.

`.gitattributes` fixes source line endings and preserves byte-exact reference data
and recorded CSVs. Exact bytes are part of replay identity. Root LICENSE and
NOTICE identify Apache 2.0 original work and retained third-party terms.

## Repository maintenance

The upstream repository is
[github.com/N0tDeb/gridsense](https://github.com/N0tDeb/gridsense). Make changes
on a feature branch, run the documented checks, and merge after CI succeeds.
The [GitHub Actions workflow](../.github/workflows/checks.yml) records Linux
full verification and Windows compatibility results. Consider branch protection
and private vulnerability reporting for maintenance. Packaging creates an
archive locally; it does not publish commits or GitHub releases. Copyright and
third-party attribution are in [NOTICE](../NOTICE).

## Continuous integration

`.github/workflows/checks.yml` defines Linux/Windows jobs with Python 3.12,
Node 24, locked installation, frontend audit and Chromium. Linux runs full
verification; Windows runs operational compatibility, with incompatible native
historical records explicitly identified rather than treated as passing. Actual
results and logs are uploaded to GitHub Actions, even when checks fail.

Strict replay pins the exact native solver identity. A different platform/native
build may reject a frozen export correctly. Inspect that evidence rather than
changing identities or tolerances to make a job pass. Verification scope is
explained in [verification](VERIFICATION.md).

## Release acceptance

Use [DEVELOPMENT.md](../DEVELOPMENT.md) to verify and package a release. Extract the
ZIP separately and follow SETUP.md with a fresh environment. Check file hashes,
installation, frontend build, native startup and essential workflows. Keep only
one authoritative application implementation and current release evidence.
The compact acceptance report states what ran and what remains unverified.
