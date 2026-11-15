# Controller assurance and electrical reference checks

The [versioned constant-PQ reference](REFERENCE_VALIDATION.md#constant-power-profile) now passes all
56 frozen comparisons with an explicit load-window/convergence profile. The
original native-default comparison below remains 52/56. These configurations
retain separate names and results; the controller studies use native defaults.

The fixed study runs against the included source and retains every outcome.
Its 32 synthetic cases are known and previously inspected. Development/reserved
labels distinguish case groups, not unseen external validation. Experimental
selectors remain evaluation-only and are not registered in the dashboard.

## What the study tests

The frozen protocol in `experiments/protocols/assurance.json` defines four
previously inspected development cases and 28 reserved cases before execution.
Reserved families change joint assumptions, not just random seeds: donor roles,
stale overestimation, in/out-of-bound demand, partial-service contracts,
pre-existing violations, unattainable downstream service and IEEE loading/stale
demand direction. Contracts and case order are fixed. No thresholds or production
policies were tuned against the results. These author-designed cases on known
models are **not an independently selected blind holdout**.

Seven selectors (five seeded defects and two unchanged controls) are evaluated
on all 32 cases: 224 reference/candidate pairs. Experimental selectors are kept separate from the registered web/API controllers. An experimental selector receives only a deep-copied PlanningView,
just like a normal controller. It cannot receive true demand through that API.
This is an information contract, not a security sandbox for malicious Python.

Each selector first receives the same fixed priming observation. The target is
another isolated-fault snapshot; the priming action is not applied to its grid.
This tests cross-observation decision caching, not a continuous two-fault physical
episode. Instances are reset between cases. All reference/candidate pairs share
identical observations, allowed actions and actual target electrical state.

An attributable detection requires the unmodified reference to pass **both**
electrical and service checks. The candidate must then violate a check, return
an unadvertised action sequence, or lose more than 0.1 kW of service. Baseline
failure is inconclusive, not a mutation detection. The full results also retain
privileged initial-feasibility and attainable-service checks to expose impossible
contracts; those truth results are never controller inputs.

| Seeded mechanism | Detection on 28 reserved cases | Interpretation |
|---|---:|---|
| Omitted feasibility filter | 2 | Unsafe full restoration preferred to safe critical-only service |
| Reversed service ranking | 16 | Deliberately obvious negative example, not a subtle independent bug |
| Reused cached action | 5 | Stale decision survives changed observations |
| Reversed switch order | 2 | Action validation rejects changed operations; not an electrical discovery |
| Ignored uncertainty policy | 2 | Wrong-policy ablation against the guarded specification; nominal is not universally wrong |
| Unmodified nominal / guarded | 0 / 0 | No false detection in these controls, not a population false-positive estimate |

All five seeded mechanisms were exercised at least once; this is not a count of
five naturally discovered production defects or evidence of general bug-detection
recall. Correct-reference pass counts are 16/28 nominal and 18/28 guarded. Retain
those denominators rather than claiming all 28 cases establish attribution.

The first reserved detection per mechanism is simplified with at most 24 extra
pair evaluations. Service contracts and priming inputs stay fixed; the primary
failure category must survive. Three cases simplify (complexity 3→0, 3→2, 5→4);
two cannot simplify under the allowed moves (3→3). Both original and reduced
cases are re-executed and compared. This is bounded greedy reduction, not global
minimality, and category preservation does not prove identical root cause.

Five exports retain inputs, received rows, selected predictions, actual node/
equipment results, switching steps, failed simplification attempts, checksums,
code hashes and solver identity. Selected predictions are stored; the full
candidate set is regenerated from the saved input during replay. Replay is not
comparison against a scripted expected success.

## Temporal status study

The physical event simulator generates 24 combinations: two timeouts,
six feedback delays and successful/failed closure. Four message-only trackers
consume each trace. This study checks restoration claims at feedback and timeout:
closed-position confirmation must have arrived, and actual restored kW must reach
the planned amount. The switch-confirmation experiment checks only for a false
restoration claim at timeout. The two studies therefore test different properties.

Confirmed control violates zero episodes; command-as-success, timeout-as-success
and inverted-position each violate 12/24. The first two have overlapping detection
sets here. These are not 36 independent failures. Successful physical closure can
still produce an unsupported claim before confirmation. Each episode has only one
command; message IDs, duplicates, feedback loss, multiple devices and protection
timing remain outside scope. Native traces and every status result are retained.
Unserved-energy totals are not ranked across different event horizons.

## Cost and unfavorable evidence

The campaign used 711 shared preparation, 511 paired execution and 204 temporal
adapter solves. Additional original rechecks used 95, reduction 328 and replay
190: **2,039 completed adapter solves** in total. These are domain snapshot calls,
not internal DSS iterations or context construction. Shared prediction work is
counted once in total cost. Per-variant first-detection costs include that variant's
share as if run alone; they must not be summed. Timings describe this machine only.

The nominal/guarded study shows unmet service and pre-existing violations.
Stale-overestimate cases pass electrical checks but only 2/4 service contracts.
Unattainable downstream cases pass no full contracts. The fixed-seed study also retains unfavorable guarded-service and
search-efficiency results; see [EVALUATION.md](EVALUATION.md). Fixed case families do not justify
field confidence intervals or a generalized mutation score.

## Additional electrical checks: an important negative result

This section describes the frozen legacy comparator. The public voltage
check now uses corrected Official-column v2; all 29 targets pass. Frozen
v1 experiments retain their earlier 692.3 target and source metadata.
[Source correction and identity limits](REFERENCE_VALIDATION.md#published-targets-and-provenance).

The healthy IEEE reference passes 29 published phase-voltage checks. The
frozen protocol includes seven load-current, fourteen P/Q, three transformer-LV
current, one LV-loading and two power-balance checks. Expected currents use
published P/Q and voltage, not OpenDSS output as their target. They are analytically
derived comparisons, **not independently published current measurements**.

**52/56 combined checks pass; four fail under the unchanged native defaults.**
The aggregate extended-reference command correctly exits 1. Tests assert this
documented outcome rather than misrepresenting it as full physical validation.

- Load 675b: 68 kW/60 kvar constant-PQ expectations differ from native results
  (about 68.827/60.734); current is 36.205 A versus the 35.779 A derived reference.
- Active-power balance residual is about −0.05213 kW, just outside the frozen
  0.05 kW numerical tolerance. The tolerance has not been relaxed.

Separate **post-hoc diagnostics**, on fresh contexts only, explain both findings.
The load's voltage is about 1.0564 pu on its 2.4 kV base, above native VMaxpu=1.05.
OpenDSS therefore uses its documented impedance fallback. At tighter solver
convergence, `P,Q = nominal(P,Q) × (Vpu/VMaxpu)^2` match the observed branch.
A separate explicit VMaxpu=1.1 control restores constant-PQ behavior and passes
the three 675b comparisons. Tighter convergence alone makes the original balance
tolerance pass. These controls do not overwrite the primary failed run or change
the bundled model, native restoration rules or reference tolerances.

The diagnostic controls pass their unchanged target checks and identify causes
within the modeled load law and numerical convergence. The original four comparisons
remain failed. No independent utility or field validation has been obtained.

This is a model-assumption finding, not evidence of a broken OpenDSS solver.
Voltage agreement alone did not establish complete load-model agreement.
Restoration outcomes use actual native powers and cap served demand as documented;
they are not silently recalculated as pure PQ. Choosing a different constitutive
model would require a versioned model change and new experimental results.

Source: [Fernandes thesis](https://sites.ecse.rpi.edu/~vanfrl/documents/mscthesis/2018_Marcelo_Thesis.pdf),
Table 13 (printed p.51), Table 18 (p.72), Table 21 (p.73); numerical facts and
tolerances are in the frozen protocol. The PDF cover/catalogue says **2017** even
though its URL and older reference metadata say 2018. The source metadata retains that URL. Source PDF SHA-256 is in the recorded check output.
[OpenDSS load documentation](https://dss-extensions.org/dss-format/Load.html)
specifies the VMaxpu fallback. No claim validates the added experimental ties,
ampacities, priority assignments, field protection or real device behavior.

## Named model-aware reference

`experiments/protocols/model_reference.json` defines a separate configuration,
`ieee13-native-model-envelope-v1`. It preserves the bundled circuit and native
VMinpu/VMaxpu values and sets numerical convergence to `1e-8`. It does not alter
the original comparator or erase its four failed checks.

The report keeps four kinds of evidence separate:

| Category | Comparisons | Interpretation |
| --- | ---: | --- |
| Published phase voltages | 29 | Independently published voltage targets |
| Declared model properties | 42 | Seven loads' type, phases, connection, rating and voltage thresholds |
| Load-law envelopes | 24 | P/Q and current bounds conditioned on published voltage and the declared native load law |
| Native power balances | 2 | Internal active/reactive balance, using uncapped load power |

For each single-phase wye load, the published-voltage allowance of
±0.003 pu is propagated through the constant-PQ and upper impedance branches.
Current bounds include the interior minimum at the branch transition. The
reference rejects intervals crossing the unsupported lower branch instead of
silently extrapolating. The original 0.05 kW/kvar numeric allowance, 0.1 A current
floor and 0.05 kW/kvar balance tolerance are retained. Expected bounds do not use
solved voltage as their target.

The three transformer-LV phase-current checks use the corresponding load-current
bounds. They are conditional analytical expectations, not independently measured
transformer currents. Checking model properties and internal balances adds no
independent field observations.

A separate sensitivity table records solve time, iteration count and active/
reactive balance for convergence tolerances `1e-4`, `1e-6`, `1e-8` and `1e-10`
at load multipliers 0.5, 1.0 and 1.25. Each run uses a fresh context. Timing starts
after the bundled circuit commands, including voltage-base initialization; it
excludes construction and is not end-to-end restoration latency. The named setting must converge and meet
the unchanged balance tolerance at all three demand levels. Full results are in
[the reference report](../experiments/model_reference_results/results.json).

The teaching adapter uses `1e-8` convergence. The five controller and search
studies use this setting and record their source, case generators, seeds, budgets,
service thresholds and analysis settings. Each protocol identifies the implementation
used for its results. The IEEE restoration adapter and the original native-default
reference comparator keep their own configurations.

## Reproduce, extend, and review

```bash
python scripts/verify.py
python experiments/run_assurance_benchmark.py --output-dir var/my-assurance-run
python experiments/reproduce_assurance.py experiments/assurance_results/reproducers/cached-action.json
python experiments/run_reference_checks.py --output var/reference-check.json
```

The last command intentionally returns 1 for the known scientific mismatches;
1 is not an installation failure. A software verification success means this
outcome was reproduced and explicitly reported, not that those checks passed.
All three reference/campaign runners refuse to replace existing evidence outputs. Windows instructions and CI use the same verification script;
actual Windows/hosted CI and independent human reviews remain pending.

Follow the [walkthrough](WALKTHROUGH.md) for a complete example and
[engineering case studies](ENGINEERING_CONTRACTS.md) for application bugs and
the model-assumption finding. The [review guide](INDEPENDENT_REVIEW.md) lists
independent checks still to be performed.
