# Automatic failure discovery and reduction

GridSense provides bounded failure search around the restoration engine.
It searches for an electrically avoidable violation, reduces demand deviations
while preserving that failure, and exports an incident pair that can be replayed
without the dashboard or its database. It does not modify or train a controller.

## What counts as a failure

The target is deliberately narrower than “something was not restored”:

1. The actual post-isolation starting state converges and passes modeled limits.
2. The controller selects a non-hold action that passed its observation-based check.
3. Applying that action at true demand converges but violates a modeled limit.
4. A feasible action in the same bounded candidate set can serve critical demand
   under that same true initial state.

The full-information reference establishes physical avoidability. It does not
establish that the alternative was identifiable from the controller's incomplete
observation. A discovered case may reveal a limitation of available information
or assumptions, not necessarily an implementation bug.

Classification is ordered: solver failure, pre-existing violation, no feasible
critical-serving restoration, controller deferred, avoidable violation, within
limits. An overloaded action with no feasible restoration is retained in the
trace as `no_feasible_restoration`, not scored as the target. “No feasible” is
relative to the implemented candidate set, not all conceivable grid operations.

Each finding separately records whether true west demand lies in reported demand
× (1 ± assumed percentage). The default search only admits points inside this
range. Unrestricted search permits assumption breaches and labels each one.
The reducer preserves that inside/outside status.

## Domain and controller information

| Variable | Default interval | Reduction reference | Who receives it? |
|---|---:|---:|---|
| Affected demand factor | 0.75–1.25 | 1.00 | Controller and evaluator |
| Actual west demand factor | 0.50–2.00 | 0.80 | Evaluator only |
| Actual east demand factor | 0.50–1.80 | 1.00 | Controller and evaluator |
| Reported west demand factor | 0.50–1.50 | 0.80 | Controller |

All four variables use a finite 0.05 grid. Bounds and reference can be changed,
subject to the scenario limits. The assumed range defaults to ±40%,
west age to 120 seconds, seed to 42, and controller to nominal. Age and uncertainty
are fixed within a search; age is a label for stale data, not a time-series model
or an empirical error distribution. The reference is an explicit reduction
target, not a fitted definition of normality.

Search tests one known isolated section on the balanced teaching feeder. It does
not invent fault locations, communication events, sensor dropouts, actuator
failures, new topologies, or arbitrary controller plug-ins.

## Directed versus uniform random search

Both methods receive the same seed, admissible grid, policy, and budget. Every
trial invokes `service.evaluate`, including both controllers, the privileged
reference, and actual electrical alternatives. No outcome is predicted by a
surrogate or supplied by the interface. A trial is a complete incident evaluation,
not one native DSS solve; incident evaluation contains multiple DSS solves.

Uniform random search samples without replacement. It samples an admissible
(actual west, reported west) pair uniformly, and independent uniform A/C factors;
this is uniform over the finite admissible domain. Rejection of duplicate draws
normally preserves this distribution. After 100 unsuccessful proposal attempts,
a deterministic unseen-point fallback guarantees progress near exhaustion; that
fallback is explicitly not a fresh uniform draw.

Directed search shares the first four draws. After initialization, every fourth
trial explores globally; the other three mutate one variable of the best-scoring
point. A mutation moves in either direction by at most a quarter of that axis's
grid length (at least one step). Invalid and duplicate points are retried. After
60 failed local proposals it tries global proposals; the same finite fallback
ensures termination. It is a simple heuristic, not a learned search policy.

The score is signed proximity to an electrical constraint: the maximum of
loading/100 − 1, normalized lower-voltage deficit, and normalized upper-voltage
excess. The voltage guidance uses the stored per-bus minimum phase voltages;
the authoritative feasibility result checks all phases. The supplied feeder is
balanced. If unbalanced models are added, guidance should include phase maxima
as well. Categories outside `within_limits`/`avoidable_violation` get score −10
so the search does not intentionally pursue already infeasible starting states.

Every valid trial consumes budget, including unsuccessful trials. Search does
not stop after the first hit. It retains the first directed failure for reduction,
or the first random failure if directed found none. This selection rule is fixed;
it does not choose whichever case makes the method look best. No repeat point
occurs within either method; points may overlap between methods as part of the
paired comparison. A small domain may be exhausted before the budget is used.

## What reduction guarantees

The signature is the selected action, the first violated constraint sorted by
kind/element, and the assumption inside/outside status. A retained case must
still satisfy the entire avoidable-violation predicate and contain that constraint.

The reducer tries one coordinate at a time: reset to reference, move halfway
toward it, or move one grid step toward it. It retains a move only after a real
evaluation preserves the signature. It restarts its scan after each accepted
move. Complexity is ordered by number of deviating variables, then total 0.05
steps from reference. Every accepted move strictly reduces this pair.

The report lists every attempted evaluation, including rejected moves. Previously
rejected points can be evaluated again after another move; these also consume
the declared budget. The default reduction budget is 48 and maximum is 96.
This straightforward approach favors inspectability over minimum solve count.

Stopping means either the budget ended or no preserving move remained in that
particular neighborhood. It does not mean global minimality, minimum causal
conditions, or optimal delta debugging. A different coordinate order or reference
may produce a different reduced case. Reduction may legitimately leave a case
unchanged. Search and reduction costs are reported separately.

## Replay, exports, and persistence

SQLite saves the search and its original/reduced incidents in one transaction.
If unchanged, those two cases share one incident ID. Other discovery trials are
retained as compact parameter/outcome traces in the search record. They do not
create hundreds of entries in the incident archive.

`Replay failure cases` performs two checks for each retained case:

- Incident replay reconstructs the recorded state and all recorded
  electrical branches, including intermediate states.
- A fresh incident evaluation reruns the controller and compares observations,
  initial state, decisions, outcomes, and failure description. The failure
  signature must still hold.

The numerical comparison uses relative tolerance `1e-7` with a unit absolute
floor. Core source, search source, circuit integrity, and DSS version are checked.
The search export has a canonical JSON SHA-256 content checksum. That checksum
detects accidental corruption; it is not a signature or protection against an
adversary who can edit the record and recompute its checksum.

Replay reproduces the two retained cases. It does not rerun every discovery or
reduction trace point. Seeds/settings/traces are exported so those searches can
be run again explicitly; IDs, timestamps, and elapsed times will differ.

From an activated environment:

```bash
gridsense search --seed 42 --budget 24 --policy nominal --output var/failure.json
gridsense reproduce --file var/failure.json --output var/reproduction.json
```

The second command needs no database. Exit 0 means matching reproduction,
1 means a compatible record produced differences, and 2 means invalid input,
integrity/compatibility rejection, or no failure to reproduce. Its JSON reports
the differences. Exported records can therefore serve as pinned regression
fixtures, without code generation or executing uploaded code.

To customize bounds, uncertainty, reference, or reduction budget, supply a JSON
object matching `SearchInput` (documented at `/docs`):

```bash
gridsense search --config settings.json --output var/failure.json
```

When `--config` is present it is authoritative; the CLI seed/budget/policy flags
are not merged into that file. Missing fields use documented defaults. To rerun
an exported search configuration, extract its `request` object to settings.json.

Compatibility is intentionally strict. Editing core/search source can invalidate
recorded reproductions. The controller-testing workflow can import a saved
reduced case into a new service-aware regression. That is a new evaluation,
separate from strict replay; see [CONTROLLER_TESTING.md](CONTROLLER_TESTING.md).

## Evidence and limits

`experiments/run_search_benchmark.py` freezes seeds 0–5, 24 evaluations per method,
two policies, and inside/unrestricted scopes: 48 method runs and 1,152 complete
incident evaluations. It retains all trials as JSON and Parquet, plus paired
per-seed outcomes and method/solver provenance. Reduction is excluded.

Report discovery success at the fixed budget, first-failure trial, and elapsed
time. No-hit runs are right-censored; the explicitly capped metric assigns them
25 for a 24-trial budget. That number is not an observed discovery time. A mean
over hits alone must be labeled and never used to hide unsuccessful searches.
Timing depends on hardware and load; paired counts are the primary comparison.

The implementation demonstrates search, physical validation, reduction,
serialization, reproducibility, and browser integration. It does not prove that
directed search is superior, estimate utility failure probability, count distinct
software defects, or establish a new research algorithm. There is no guarantee
that a finite search finds a failure even when one exists.

### Six-seed comparison

In the [recorded six-seed experiment](../experiments/search_results/SUMMARY.md),
both methods found nominal failures in 2/6 inside-range runs and 6/6 unrestricted
runs. Neither found a guarded failure in an inside-range run; both found one in
all six unrestricted guarded runs. Those no-hit results do not certify the
guarded policy.

Random search had a lower mean capped first-failure trial in all three conditions
where failures were found. Directed search generated more failing trials after
discovery: 162 in total versus 51 for random across the same 576-trial budget per
method. These are correlated scenarios, not 162 distinct bugs. These results
support local concentration around failure regions, not faster initial discovery
or a generally superior search algorithm. No parameters were retuned after seeing
these results. Keep random search as a serious baseline.

### Paired fixed-seed evaluation

The [frozen protocol](../experiments/protocols/quality.json) uses seeds 100–107
and 16 trials per method. It retains all 1,024 trials, paired whole-seed bootstrap
intervals, measured adapter costs, and separately budgeted reduction/replay. It
is a separate fixed-budget comparison. See the [generated results](../experiments/quality_results/SUMMARY.md)
and [methodology](EVALUATION.md). No-hit capped trial 17 is not a measured
discovery time; repeated failing scenarios are not new defects.
