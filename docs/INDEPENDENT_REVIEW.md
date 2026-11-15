# Independent review

Independent software and power-systems reviews are pending. No human sign-off or
external reviewer attribution is implied by automated tests. The project can be
used as a local simulation/portfolio application within its documented scope.

## Review procedure

1. Extract the release into a new directory and follow SETUP.md without author help.
2. Record platform, Python/Node/native versions and release file hashes.
3. Run `python scripts/verify.py` into a new output directory and retain its reports.
4. Exercise the [feature journeys](FLOW_VERIFICATION.md), including interruptions,
   invalid input, export integrity and recovery.
5. Complete the applicable [software](reviews/software-review-template.md) or
   [power-systems](reviews/power-systems-review-template.md) form.

Use a developer familiar with concurrency, data integrity and web application
flows for software review, and an engineer/researcher experienced in distribution
power flow for the electrical model.

## Electrical questions

Independently inspect the circuit source, phase mapping, fixed taps, voltage bases,
experimental ratings and every intermediate switching check. Transcribe the
[reference targets](REFERENCE_VALIDATION.md) and examine the 692.3 provenance
and source-PDF identity limits. Reproduce native-default 52/56, the declared
constant-power 56/56 and model-aware evidence categories. Explain whether each
configuration and tolerance is appropriate for its stated claim.

Do not count conditional envelopes, internal balances or declared model properties
as independent physical observations. Guarded sampling does not cover every
continuous uncertainty point. Protection, transients and utility suitability
remain outside the implemented model.

## Software questions

Inspect controller/evaluator information separation, native worker lifetime,
request cancellation, revision/idempotency rules, database transactions and strict
replay. Try a trusted custom selector through the documented interface. Check
complete study denominators, invalid baselines, unsuccessful searches and budget
exhaustion. Consult [architecture](ARCHITECTURE.md), [engineering contracts](ENGINEERING_CONTRACTS.md),
[walkthrough](WALKTHROUGH.md), [model](MODEL.md) and [limitations](LIMITATIONS.md).

## Required evidence

Return a dated report with relevant experience, environment, commands, actual
results, exact reproductions, confirmed defects, concerns and acceptable claim
boundaries. State whether public attribution is permitted. Review completion
requires a real report; automated preparation does not fill reviewer fields.
Preserve failing cases, correct confirmed defects, add meaningful regressions
and rerun affected evidence. Record explicitly retained limitations.
