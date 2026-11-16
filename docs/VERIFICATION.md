# Verification and acceptance

Each full verification run produces `verification.json` and supporting logs in
its chosen output directory. The source ZIP release command also generates a
`docs/verification/summary.json` report and `RELEASE_MANIFEST.json` for that
specific verified source snapshot; these are generated outputs, not evergreen
proof about later commits. Examine the
[latest GitHub Actions runs](https://github.com/N0tDeb/gridsense/actions/workflows/checks.yml)
for current hosted execution results.

## Run the checks

Follow SETUP.md, including frontend dependencies and Chromium, then run:

```bash
python scripts/check_repository.py
python scripts/verify.py --output-dir var/verification
```

The verifier records commands, exit codes, timing, JUnit backend outcomes,
structured Playwright outcomes and native results. It refuses a nonempty output
folder. `--skip-browser` is explicitly incomplete. `--campaign` additionally
executes the full seeded-controller campaign. Logs and browser captures stay in
ignored `var/`; they are not source repository content.

## Acceptance scope

| Area | Required check |
| --- | --- |
| Repository | Required files, source paths, local Markdown links, packaging boundaries and credential/private-key patterns |
| Dependencies | Fresh locked Python/Node installation and `pip check`; frontend advisory audit |
| Static/build | Python lint/format, frontend formatting, TypeScript and production build |
| Backend | Electrical, controller, API, storage, concurrency, integrity and regression tests |
| Browser | Complete Chromium feature journeys, mobile layout, keyboard/focus, invalid input and request recovery |
| Native runtime | Frontend/API readiness, real electrical results, six strict export/replay flows and topology geometry |
| Persistence | Abrupt server termination/restart, pending command preservation and identical retry |
| Study evidence | Current source/protocol fingerprints, complete denominators, raw table agreement and portable reproducers |
| Packaging | One project root, complete manifest hashes/CRCs, no dependencies/caches/databases or older ZIPs |
| Fresh extraction | Separate source tree, new dependencies, build/tests/native startup and no original-workspace imports |

[Feature coverage](FLOW_VERIFICATION.md) maps the main journeys to test files.
The full suite's counts can increase as maintained regressions are added.
The summary separates passed, failed, skipped, errors and flaky outcomes.

## Electrical interpretation

The public voltage reference has 29 targets. The declared constant-power profile
checks 56 comparisons. The native-default audit retains four known failures and
is labelled `known-reference-mismatch`, rather than passing physical validation.
The verifier fails if that mismatch set changes. Model-aware categories and
configuration controls have distinct meanings. [Reference validation](REFERENCE_VALIDATION.md).

Source, model and native solver identity are required for strict replay. Different
native builds may reject frozen records correctly; current-code evaluation is
separate. Study consistency checks do not claim that every campaign was rerun.
The summary distinguishes actual execution from checking retained evidence.

## Limits on completion claims

A passing job verifies only the checks executed on its platform. The Linux CI
job runs full local verification, including frozen native replay. The Windows
CI job runs operational compatibility checks and explicitly reports historical
Linux-native records that cannot be strictly replayed under a different OpenDSS
build; this is not equivalent to cross-platform scientific validation. Consult
[GitHub Actions](https://github.com/N0tDeb/gridsense/actions/workflows/checks.yml)
for current results and retained run artifacts. Native steady-state checks do not
establish field safety, protection behavior or transient performance. No claim of
independent field certification is made. See [limitations](LIMITATIONS.md) and
[security](../SECURITY.md).

The repository is complete source with explicitly documented dependencies. No
previous ZIP, development directory, conversation or runtime database is required.
