# Electrical reference validation

GridSense separates published targets, declared model properties, conditional
analytical envelopes and internal numerical invariants. Passing one category
does not establish the others. All named profiles are included and reproducible
from this repository, with no older project archive required.

| Check | Configuration | Result in included evidence | Meaning |
| --- | --- | --- | --- |
| Public voltage reference | Native circuit/defaults; Official-column dataset | 29/29 | Healthy voltage magnitude agreement within 0.003 pu |
| Native-default extended audit | Frozen 29-voltage dataset and 27 supplementary checks | 52/56 | Four explicit model/comparator mismatches |
| Constant-power profile | Frozen targets; 675b VMaxpu=1.10; convergence=1e-8 | 56/56 | Agreement under the declared constant-PQ configuration |
| Native model-aware profile | Native load window; convergence=1e-8 | 29 + 42 + 24 + 2 checks pass | Published voltages, properties, conditional envelopes and balances, reported separately |

## Published targets and provenance

The public check uses `backend/gridsense/references/ieee13_published_v2.json`.
Its source is [Table 13, Official Results column](https://sites.ecse.rpi.edu/~vanfrl/documents/mscthesis/2018_Marcelo_Thesis.pdf)
of Marcelo de Castro Fernandes's thesis: printed page 51, physical PDF page 53.
The cover year is 2017; the hosted filename contains 2018. Three regulator-output
values labeled 650 are excluded because of bus-mapping ambiguity.

The included target for bus 692 phase C is **0.9778 pu**. The frozen extended-audit
dataset uses **0.9777 pu**, from the table's adjacent OpenModelica column. The
other 28 targets agree. Both values pass the unchanged voltage tolerance, so
this target difference does not explain the four extended-audit failures.
The public target file records the distinction. Frozen study inputs are retained
byte-exact to preserve their recorded identities.

The source PDF identity recorded for the inspected public dataset is:

```
301d616ae14dad5d5677d2b8ad8a648cecc7664c98b8aa47593825cf02c33acb
```

Frozen audit metadata also records a different source-PDF digest. Its original
PDF bytes are unavailable for comparison, so that source identity remains
unverified. The public dataset pins the inspected copy; neither metadata nor
software checks establish an independent expert review. The copyrighted thesis
is referenced rather than bundled. IEEE circuit source and license information
are under `backend/gridsense/circuits/ieee13/`.

The public helper verifies dataset/model fingerprints and rejects non-finite
native voltages. It uses the same unmodified native circuit and defaults as the
restoration adapter, without adding restoration ties to the reference circuit.

## Native-default audit

The extended audit adds seven load-current, fourteen P/Q, three transformer-LV
current, one transformer-loading and two internal power-balance comparisons to
the frozen 29 voltages. Derived current targets use published P/Q and voltage;
they are not independent current measurements.

Three failures involve load 675b. It declares Model=1, 68 kW and 60 kvar, but its
solved voltage exceeds native VMaxpu=1.05 on the load's rated voltage base. Above
that threshold the documented native load law uses an impedance branch.
The fourth failure is a small active-power balance residual under the native
convergence setting. [Native load law](https://dss-extensions.org/dss-format/Load.html).

| Quantity | Expected | Native-default actual | Frozen allowance |
| --- | ---: | ---: | ---: |
| 675b current, A | 35.779388 | 36.204901 | 0.357794 |
| 675b active power, kW | 68 | 68.827081 | 0.05 |
| 675b reactive power, kvar | 60 | 60.733520 | 0.05 |
| Active-power balance, kW | 0 | -0.052129195 | 0.05 |

`experiments/run_reference_checks.py` intentionally returns exit 1 and retains
these four failures. The full verifier labels this `known-reference-mismatch`
and fails if the set changes. It never reports the native audit as 56/56.

## Constant-power profile

`ieee13-constant-pq-reference-v1` applies only two explicit settings:

| Setting | Native audit | Constant-power profile |
| --- | ---: | ---: |
| Load.675b VMaxpu | 1.05 | 1.10 |
| Solver convergence | 1e-4 | 1e-8 |

All target values, comparator tolerances, nominal powers, taps and other native
inputs remain frozen. All 56 comparisons use one configured healthy solve.
Configured 675b power is approximately 68.000000 kW/60.000000 kvar and current
35.763523 A. The active balance residual is approximately -0.000007091 kW.
Every run also reproduces the native-default 52/56 result.

This profile is a declared load-window change for the nominal-PQ comparison.
Production/restoration inputs retain native defaults. The settings were selected
after examining the mismatch, so the result is a diagnostic comparison rather
than blind confirmation or field validation.

## Configuration controls

The isolated sensitivity runner evaluates the same 56 frozen targets:

| Control | Convergence | 675b VMaxpu | Passed |
| --- | ---: | ---: | ---: |
| Native defaults | 1e-4 | 1.05 | 52/56 |
| Precision only | 1e-8 | 1.05 | 53/56 |
| Wider load window | 1e-4 | 1.10 | 56/56 |
| Both settings | 1e-8 | 1.10 | 56/56 |

Independent native contexts isolate configuration changes. Saved diagnostic
reports are compared against fresh execution, including settings, finite values,
targets, tolerances, counts and flags. Precision explains the balance residual;
it does not remove the constitutive-law difference under the native load window.

## Model-aware profile

`ieee13-native-model-envelope-v1` preserves native load thresholds and solves at
1e-8. It reports four categories rather than treating their total as independent
physical observations:

| Category | Comparisons | Interpretation |
| --- | ---: | --- |
| Frozen published voltages | 29 | Voltage targets with the stated 692.3 provenance distinction |
| Declared load properties | 42 | Seven loads' model, phases, connection, rating and thresholds |
| Conditional load-law envelopes | 24 | P/Q and current bounds from published voltage allowance and declared native load law |
| Internal balances | 2 | Numerical active/reactive conservation |

A convergence study checks four tolerances at three demand levels. These checks
share the native solver and declared model assumptions; they do not validate
experimental restoration ties, ratings, protection, transients or utility operation.

## Reproduce

After SETUP.md, use new output paths:

```bash
python -m gridsense.cli validate-feeder
python experiments/run_reference_checks.py --output var/native-reference.json
python experiments/run_configured_reference.py --output var/constant-power.json
python experiments/run_reference_sensitivity.py --output var/reference-controls.json
python experiments/run_model_reference.py --output var/model-aware.json
```

Included results and protocols live under `experiments/`. `python scripts/verify.py`
runs the named checks and verifies saved configured/control evidence against actual
native execution. These experiments are bounded model checks, not independent
field validation; additional evidence is required before expanding claims.
