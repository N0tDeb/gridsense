# Repository and release

The `gridsense/` directory is the repository root. It contains the complete
application, locked dependencies, tests, model data, license notices, documentation
and reproducible studies. It needs no preceding ZIP, patch or external project folder.

## Source and generated files

Commit source, manifests, lockfiles, required assets, tests and frozen study inputs.
The application builds the dashboard into `frontend/dist/`; regenerate it with
`npm ci` and `npm run build`. Do not commit environments, `node_modules`, local
browser binaries, runtime databases, secret configuration or test captures.
`.gitignore` and the source ZIP packager enforce these boundaries.

`.gitattributes` fixes source line endings and preserves byte-exact reference data
and recorded CSVs. Exact bytes are part of replay identity. Root LICENSE and
NOTICE identify Apache 2.0 original work and retained third-party terms.

## Initialize and publish

After reviewing the extracted source, create an empty repository under the desired
GitHub account. Then, from this directory:

```bash
git init -b main
git add .
git status --short
git commit -m "Add GridSense"
git remote add origin https://github.com/YOUR_ACCOUNT/YOUR_REPOSITORY.git
git push -u origin main
```

Replace the placeholders with the actual repository. No remote publication is
performed by packaging. Configure branch protection and private vulnerability
reporting on GitHub after repository creation. The copyright holder is N0tDeb;
see [NOTICE](../NOTICE).

## Continuous integration

`.github/workflows/checks.yml` defines Linux/Windows jobs with Python 3.12,
Node 24, locked installation, frontend audit, Chromium and the complete verifier.
It uploads actual verification logs even on failure. Run status must be observed
on GitHub; having a workflow file does not establish a hosted CI pass.

Strict replay pins the exact native solver identity. A different platform/native
build may reject a frozen export correctly. Inspect that evidence rather than
changing identities or tolerances to make a job pass. Actual platform execution
and external-review status are listed in [verification](VERIFICATION.md).

## Release acceptance

Use [DEVELOPMENT.md](../DEVELOPMENT.md) to verify and package a release. Extract the
ZIP separately and follow SETUP.md with a fresh environment. Check file hashes,
installation, frontend build, native startup and essential workflows. Keep only
one authoritative application implementation and current release evidence.
The compact acceptance report states what ran and what remains unverified.
