# Live-controller boundary challenge

This study uses 25 internal synthetic cases: twelve paired variations and one
healthy negative control. Each case runs with off, nominal and guarded policies,
for 75 episodes and 1,275 native physical snapshots. Every episode has the same
16-second horizon. Case settings and physical events are shared across policies;
only the planning policy changes. Controller bounds, including each case's command
or solve cap, are identical across the three policies.

The inputs and source identities are frozen. This is an inspected engineering
case set, not an external, blind or statistically representative test set.
A retained comparison implementation supplies separate failure/accounting
fixtures; its results are not attributed to the production controller.

## Command allowance contract

Each plan must fit the remaining command allowance as well as the configured
sequence length. Restoring through a tie and returning to normal can require
more operations than the remaining budget. When recovery cannot fit, keeping
checked backup supply can avoid an otherwise unnecessary interruption.
Confirmation, availability and fresh electrical checks still apply at every step.

The nominal `command-cap-2` case records 0.278 kWh unserved and one command
under the production controller. Its separate frozen comparison records
3.056 kWh and two commands, with a 1,000 kW interruption after opening the tie.
The guarded `command-cap-1` production case waits for repair and uses its one
allowed command to reconnect normal supply. These are case-specific comparisons,
not estimates of general service improvement or a blind evaluation.

The [frozen comparison outcomes](../experiments/challenge_discovery/results.json),
[complete traces](../experiments/challenge_discovery/episodes.jsonl.gz),
[freeze](../experiments/challenge_discovery/freeze.json) and dependency-source
fixtures support a distinct source/trace/accounting check. That checker uses the
frozen input schema without injecting current defaults. It does not execute that
controller as the current application or relabel its results as current outcomes.

## Current-controller results

Totals below sum 25 artificial episodes per policy: 400 known simulated seconds
per policy, with zero unknown intervals. They are not field outage rates or
estimates of a deployment population. A sample at the final horizon has no energy
interval; endpoint service and accumulated energy answer different questions.

| Policy | Unserved kWh | Critical kWh in compliant states | Violating snapshots | Commands | Planning solves | Median episode wall time |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Off | 110.139 | 4.444 | 0 | 0 | 0 | 0.14 s |
| Nominal | 38.424 | 34.022 | 0 | 53 | 409 | 1.01 s |
| Guarded | 65.064 | 29.356 | 0 | 65 | 7,257 | 2.23 s |

The run completed on 12 October 2026 in 101.89 seconds. It used
8,941 native adapter calls, including 1,275 physical snapshots. Guarded used
more computation and left more demand unserved than nominal. Zero violations
here do not establish general safety: the separate [36-episode comparison](SESSION_EVALUATION.md)
retains three nominal and one guarded violating snapshots.

Sixteen guarded decisions exhausted their deliberately small solve budgets;
no nominal decision did. Exhaustion leaves unchecked alternatives unknown and
makes no optimality claim. Both active policies finish one lost-feedback case
with an unresolved command. None are omitted from the totals. Off avoids
violations by leaving interrupted demand disconnected.

The controller uses declared switching times, future held-bound checks and
transition energy; it does not receive private actuator settings. Newly observed
availability changes can supersede the cooldown, while pending confirmation and
resource caps remain hard limits. [Execution planning](EXECUTION_PLANNING.md)
describes the objective and conservative overload restrictions.

| Case | Off unserved kWh | Nominal unserved kWh | Guarded unserved kWh |
| --- | ---: | ---: | ---: |
| healthy-control | 0.000 | 0.000 | 0.000 |
| confirmation-deadline-2 | 4.167 | 1.111 | 2.153 |
| confirmation-deadline-3 | 4.167 | 1.389 | 2.500 |
| position-freshness-2 | 4.167 | 1.111 | 2.597 |
| position-freshness-3 | 4.167 | 0.278 | 1.528 |
| refault-order-5 | 4.167 | 0.278 | 1.528 |
| refault-order-6 | 4.167 | 0.556 | 1.806 |
| overlap-clearance-6 | 4.167 | 0.556 | 1.319 |
| overlap-clearance-16 | 4.167 | 0.278 | 1.528 |
| recovery-demand-1.3 | 5.000 | 0.639 | 1.333 |
| recovery-demand-1.5 | 5.556 | 0.694 | 1.389 |
| donor-demand-1.7 | 4.167 | 1.896 | 2.746 |
| donor-demand-1.9 | 4.167 | 2.000 | 2.971 |
| native-budget-14 | 4.167 | 0.556 | 4.167 |
| native-budget-15 | 4.167 | 0.556 | 4.167 |
| command-cap-1 | 4.167 | 0.278 | 1.389 |
| command-cap-2 | 4.167 | 0.278 | 1.528 |
| decision-cap-1 | 4.167 | 0.278 | 1.528 |
| decision-cap-2 | 4.167 | 0.278 | 1.528 |
| source-end-repair-15 | 10.625 | 10.625 | 10.625 |
| source-end-repair-16 | 10.625 | 10.625 | 10.625 |
| transformer-end-repair-15 | 1.667 | 1.667 | 1.667 |
| transformer-end-repair-16 | 1.667 | 1.667 | 1.667 |
| feedback-loss-false | 4.167 | 0.556 | 1.250 |
| feedback-loss-true | 4.167 | 0.278 | 1.528 |

Three-second-old position rows exceed the two-second freshness limit. The
controller can therefore report `awaiting_measurements` even when native physical
supply exists. It is not allowed to substitute simulator truth for missing received
evidence. Repair at the horizon can have the same accumulated unserved energy as
repair one tick earlier, although final service differs after a confirmed action.
First recovery delay records the first complete recovery; it does not certify
that later supply remains uninterrupted.

## Evidence and reproduction

- [Protocol](../experiments/protocols/session_challenge.json) and
  [source freeze](../experiments/protocols/session_challenge.freeze.json).
- [Complete outcomes and costs](../experiments/challenge_results/results.json),
  [all-case table](../experiments/challenge_results/outcomes.csv), and
  [compressed full traces](../experiments/challenge_results/episodes.jsonl.gz).
- The report checker verifies all expected case/policy pairs, fixed horizons,
  frozen identities, table consistency, per-tick solve caps and final command counts.
  It independently sums native physical frames for raw and feasible energy,
  unknown intervals, violating samples and duration, and counts actuation events.

```bash
python experiments/run_session_challenge.py --output-dir var/session-challenge
python experiments/run_session_challenge.py --output-dir var/session-challenge --verify-report
python scripts/check_challenge_discovery.py
```

Use a new output directory. The first command executes the current controller;
the others check stored evidence. The discovery check does not replay old results
through the current controller. Run campaigns without other native jobs if measuring
cost. Execution order is fixed (case, then off/nominal/guarded); single-host wall
measurements have no repeated-run confidence interval or ordering correction.
Adapter calls are not DSS internal iterations. Their counts are more portable
than these timings. The separate session study supplies the bounded permutation
and finite-grid comparisons, with their own stated costs and limitations.
