# Evaluation methodology

The [clocked-session comparison](SESSION_EVALUATION.md) and
[boundary challenge](SESSION_CHALLENGE.md) evaluate the live controller with
common fixed horizons. They retain complete electrical frames, service losses,
unresolved confirmations and computational costs. A separate frozen comparison
supports boundary-case failure/accounting checks without relabeling those outcomes
as the production controller's results.

Each study identifies its protocol and source. Fixed case groups and seeds have
been inspected: these are reproducibility experiments on known synthetic models,
not unseen external validation. Protocol revisions, pin times and predecessor
hashes are scientific integrity metadata; they do not require another project
archive. Source changes require actual affected reruns rather than hash edits.

## Questions

1. Do graph switching operations change actual OpenDSS results?
2. Can a topologically connected restoration violate electrical constraints?
3. Can different routes and partial restoration win in different load conditions?
4. What is the trade-off between trusting stale demand and stress-checking an
   assumed range?
5. Can a recorded incident and every alternative branch be reproduced?
6. Can bounded search find avoidable electrical violations, and does it improve
   discovery over uniform random search under equal evaluation budgets?
7. Can a case be simplified while preserving the same physical failure?

## Three separate kinds of evidence

**Tests** exercise behavioral contracts and regressions: native switch state,
bus voltages, load power, ratings, isolation, radiality, context independence,
information separation, persistence, replay, validation, and real browser flows.
They do not establish utility realism.

Live-session tests additionally exercise logical-time ordering, delivered-information
separation, alarm evidence, delayed/duplicate rows, held demand, concurrent revision
conflicts, rollback, restart pause and full episode replay. The CLI example and
runtime API check demonstrate these contracts. They are software verification,
not an experiment establishing fault-detection accuracy or sensor calibration.
The controller/search study fingerprints are separate from the session modules;
their retained results remain tied to the exact controller/electrical inputs.

Clocked restoration has its own [fixed-horizon comparison](SESSION_EVALUATION.md):
12 physical cases under off, nominal and guarded policies, command failures,
separate permutation enumeration and a dense finite uncertainty check. Its
15-point six-load policy differs from the three-point west-demand policy used
by the snapshot studies below. The clocked controller receives native measured
load estimates; comparisons share scenario and transport settings, while later
observations can differ because earlier policy actions changed supply.

**Demonstrations** are curated explanatory scenarios. Their purpose is to make
the mechanism understandable, not to estimate average performance.

**The benchmark** enumerates a stated grid of operating conditions and retains
every outcome. It measures behavior on that grid. The provided feeder and
parameter choices are not an independent deployment population.

## Controllers and fairness

Nominal and guarded see the exact same observation in each case. They differ
only in whether stale west demand is tested at the declared lower and upper
values. The oracle sees actual demand and is labeled privileged throughout.
No controller is allowed to inspect evaluator outcomes before deciding.

All controllers share the same switching candidate set and electrical checks.
The “hold isolation” candidate is included. The oracle is not claimed globally
optimal; it is the reference within the declared candidate set.

## Metrics

- Restored affected demand, critical served demand, and total unserved kW.
- Voltage and current-rating violations, separately from restored demand.
- Maximum equipment loading, lowest energized voltage, and switching operations.
- Mean feasible restored kW: zero restoration credit when modeled limits fail,
  reported together with raw restored kW and explicit violation counts.
- Replay agreement, including intermediate states.

The snapshot study does not estimate energy not served or restoration time.
The separate bounded event experiment integrates unserved demand only over its
recorded event horizon. That horizon changes with event timing, so its raw energy
totals must not be used to rank traces with different durations. Neither study
estimates SAIDI, monetary savings or customer counts.
No accuracy, F1, predictive lead time, or calibration score is reported: no ML
model is trained in this release.

## Benchmark

`python experiments/run_benchmark.py` evaluates:

- West factors: 0.6, 0.8, 1.0, 1.3, 1.6, 1.9.
- East factors: 0.7, 1.0, 1.3, 1.6.
- Telemetry regimes: current, stale with a wide assumed range, stale with a narrow
  assumed range. Exact construction is in the script and every raw result.

That is 72 electrical scenarios and 216 controller outcomes. Each row records
whether actual west demand lies within the declared uncertainty range. Results
are exported as JSON and Parquet, with a complete model/implementation/solver
manifest and a generated summary. Do not edit the summary numbers by hand.

The interactive demand sweep answers a different question: with observations
held fixed, how does a recorded decision behave as hidden actual west demand
changes? Nine plotted points are observed failure samples, not a mathematically
certified boundary.

## Failure-search comparison

The paired search experiment is separate from the 72-case controller grid.
Its frozen script compares directed and uniform random search at seeds 0–5,
24 trials per method, with nominal/guarded controllers and inside/unrestricted
uncertainty scopes. All 1,152 complete incident evaluations are retained.
The searcher has evaluator truth; controller information remains unchanged.

Compare runs that found a failure, paired first-failure trials, and costs. No-hit
runs remain visible and are assigned 25 only for the explicitly capped metric.
Do not infer a speed advantage from failing-trial counts or a cherry-picked seed.
The first default demonstration uses seed 42; it is separate from these benchmark
seeds. See the [search methodology](FAILURE_SEARCH.md) and
[complete comparison](../experiments/search_results/SUMMARY.md).

Reduction is evaluated independently through preservation of the action,
violated constraint, and assumption status; decreasing input deviations; and
replay of both cases. Reduction cost is not charged to either discovery method.
The benchmark contains six seeds per condition, not enough to claim broad
statistical superiority. That search study uses one custom topology and no field cases.

## Limits and useful next experiments

No field measurements are supplied. The IEEE13 study checks 29 reference
phase-voltage magnitudes and adds a second, explicitly modified topology. This
does not independently validate its restoration assumptions or all electrical
quantities. A human review of those assumptions remains valuable; broader fault,
load and model-mismatch experiments are needed before expanding claims.

The [constant-PQ reference v1](REFERENCE_VALIDATION.md#constant-power-profile) passes all 56 existing
healthy-circuit comparisons under a separately frozen load-window/convergence
profile. It retains the native-default 52/56 comparison and all original targets
and allowances. Its diagnostic selection and derived/internal checks do not
provide independent field validation or revise the controller-study model.

Uncertainty bounds need empirical or explicit physical justification before
the guarded policy becomes more than a controlled stress experiment. Adding
active measurement requests would additionally require realistic availability,
latency, and cost assumptions.

There is no claim that this engineering tool or policy is research-novel.
Published restoration methods and platforms such as GridAPPS-D are prior art.
The current value is an inspectable implementation and reproducible evidence.

## Transfer and testing usefulness

The transfer benchmark retains 192 portable cases / 576 controller outcomes over six
fixed seeds, the custom feeder and the modified IEEE13 feeder, two whole-line
fault positions each. Development and transfer groups are labelled. Integration
smoke checks preceded the benchmark; this is not a blind external holdout. No
controller tuning was performed on these transfer results.

Categories distinguish pre-existing violations, unattainable restoration within
the bounded action set, assumption breaches, information-limited violations,
service shortfall, and the deliberately poor hold control. Original first-failure
search statistics are retained. A signature analysis reports observed signature diversity
without treating repeated overloads as distinct bugs. Six temporal searches
report first-hit costs, reduction evaluations and actual strict-replay results.

The guarded controller is not a universal improvement: it can reduce violations
while losing service. The experiment preserves those unfavorable results. Neither
high safety counts for hold nor repeated discovery of the seeded temporal defect
is evidence of a superior restoration controller. See
[full results](../experiments/verification_results/SUMMARY.md) and
[controller/testing methodology](CONTROLLER_TESTING.md).

## Numerical precision and ranking

Service is rounded to 0.1 kW before ranking. Rounding alone does not remove all
solver sensitivity near a bucket boundary. In case `teaching-feed_a-104-2`, a
separate 1e-4 convergence control places the two full-service routes on opposite
sides of 2804.95 kW. The declared 1e-8 solve places both at the same 2805.0 kW
ranking value; predicted loading then selects the east tie. Both routes satisfy
the service contract in this case. Because received west demand exceeds actual
demand, the lower predicted-loading choice does not have the lower true loading.
Numerical consistency and decision quality under imperfect information are
separate questions. Solver settings and rounding rules are recorded assumptions,
not proof of ranking stability for every input.

## Fixed-seed evaluation with uncertainty intervals

`experiments/protocols/quality.json` fixes the study inputs before execution. It names the exact core,
search and harness fingerprints, seeds, budgets, groups and bootstrap settings.
The runner uses the declared generator and service contracts. It rejects changes
to the protocol or source. Controllers, uncertainty bounds, service thresholds
and search settings were not tuned using its outcomes.

Search uses seeds 100–107, 16 complete incident trials per method, two controllers
and two uncertainty scopes: 64 method runs / 1,024 trials. Each seed pairs the
methods; execution order alternates. One unscored warm-up is separate. Instrumented
adapter calls count precondition and intermediate-state evaluations. These are
not DSS internal iteration counts. Costs through the first hit and through the
whole run are retained. Seed 100 is separately allocated 24 reduction trials in
every policy/scope, with strict replay after any retained failure. No-hit records
are exported too; they contain no failure to reproduce.

Controller evaluation uses seeds 100–105 with the declared generator, four
feeder/fault groups, eight points per seed/group and three controllers:
192 cases / 576 outcomes. Outcomes retain the original all-case denominator and
also report initially feasible, truth-attainable cases. The latter is a privileged
bounded-action reference, not an information-matched controller. Zero eligible
cases are reported as N/A, never as 0% or 100% success.

Paired uncertainty intervals resample whole seeds 10,000 times with seed 734.
Trials from one adaptive search and controller cases within a seed are not
treated as independent samples. Report paired first-failure differences and
controller electrical/service differences together with denominators. These are
small descriptive percentile-bootstrap intervals with no multiple-comparison
correction, not calibrated operational risks. A [0,0] interval in a no-hit group
reflects censoring at this budget, not proof of equal performance or safety.

These are **fixed seeds on known models**, not external blind validation. See
[generated summary](../experiments/quality_results/SUMMARY.md), full JSON/Parquet,
and the complete failed or service-limited outcomes. No-hit searches and
unfavorable controller trade-offs remain part of the reported results.


## Native solve reuse

Eight frozen planning inputs vary demands independently across six load groups
and compare connected-demand reuse with a full-demand-key reference. Each input
runs at 192 and 2,048 native calls: 16 pairs, or 32 searches. Thirteen pairs
complete both searches and agree; budget-limited differences remain recorded.
Demand-sample probes separately check electrical predictions and disconnected
requested-demand accounting. Both implementations share native physics and the
objective. These are synthetic engineering inputs, not externally blind cases.
See [native reuse](NATIVE_REUSE.md) for results and reproduction commands.

## Reproduce the included studies

Use fresh output directories. All commands run from the project root with the
installed environment. Run the search comparison before transfer analysis:

```bash
python experiments/run_benchmark.py --output-dir var/grid-study
python experiments/run_search_benchmark.py --output-dir var/search-study
python experiments/run_verification_benchmark.py --output-dir var/transfer-study --search-results var/search-study/results.json
python experiments/run_quality_benchmark.py --output-dir var/quality-study
python experiments/run_assurance_benchmark.py --output-dir var/assurance-study
```

The bundled outputs are respectively `experiments/results/`, `search_results/`,
`verification_results/`, `quality_results/`, and `assurance_results/`. Each study
retains its complete JSON/Parquet data and summary. Runners refuse nonempty
output directories. Do not run studies concurrently when comparing elapsed times.
Counts and paired outcomes are more portable than runtime measurements.

The paired-search runner uses a fresh worker process per seed pair. The
fixed-seed runner also uses a fresh worker for each controller seed-group. Jobs
run sequentially, retaining the same generators, paired method order, budgets
and reduction rules. This bounds process lifetime because the pinned native
wrapper retains created contexts. Method timings exclude worker startup; total
campaign elapsed time includes it. The native wrapper can still retain contexts throughout a long individual job. Prefer bounded
jobs when writing additional headless campaigns.
