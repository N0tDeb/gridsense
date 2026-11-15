# Controller testing

GridSense tests a restoration controller as a software component. A test checks both electrical limits and the amount of service restored.
Saved failures can be replayed or used to compare a controller change. Scope is defined in [LIMITATIONS.md](LIMITATIONS.md).

## Reproduce history or evaluate a change

| Operation | Input | What it does |
|---|---|---|
| `reproduce` | Failure-search export | Requires the original source/solver; reruns retained decisions and electrical branches |
| `verify-run` | Regression/event export | Requires the recorded harness/solver and checksum; compares recorded fields |
| `regress --file case.json` | Portable case | Runs current baseline/candidate against the same observations and hidden truth |
| `regress --file previous-run.json` | Saved regression | Intentionally runs the current candidate against the previous candidate's **recorded outcome**, preserving source provenance |
| `regress --file old-search.json` | Search export | Imports reduced scenario inputs into a new explicit service contract; does not call this historical reproduction |

Cross-version evaluation accepts an older harness identifier; historical replay
rejects it. A saved regression includes its portable case, explicit minimum
restored/critical kW, both outcomes, permitted controller inputs, all candidate
predictions, source fingerprint, DSS version and integrity checksum. A repeated
cross-version comparison retains the immediate historical baseline and its source
record checksum. A checksum detects accidental alteration, not malicious signing.

The files in `experiments/examples/` match this source. Editing fingerprinted
modules requires generating new records. A saved input may be evaluated with
current code even when its original run cannot be strictly replayed.

Acceptance requires: the candidate meets electrical **and** service constraints;
it introduces no electrical failure relative to a passing baseline; and critical,
restored and total served kW do not decrease by more than 0.1 kW. This conservative
gate can reject an intentional safety/service trade-off: inspect it and revise the
test contract deliberately, rather than hiding the trade-off in a scalar score.
The unchanged scenario may still be unattainable; failure of a test is not by
itself proof of a software defect. Comparing different adapter/solver versions
is an observed system regression, not causal attribution solely to controller code.

`hold-v1` is a negative control, not a competitive restoration policy. It can
pass electrical checks and fail service requirements. `guarded-v1` checks
the lower, nominal and upper demand assumptions; it does not guarantee an uncertainty
interval, and conservatism can worsen service on the modified IEEE model.

## Add a controller without changing the simulator

`controllers.Controller` requires `id` and `select(PlanningView) -> Action`.
The view contains observed demand and candidate electrical predictions only;
it never receives the `PortableCase`, plant, or hidden actual load. The runner
checks that the selected action exactly matches an advertised action, then
executes it on hidden truth. Deep copies keep controller mutation out of the
shared comparison view. Python plugins are trusted local code, not a sandbox.
The HTTP service accepts an allowlisted controller ID, never executable uploads.

```python
from gridsense.cases import PortableCase
from gridsense.regression import evaluate_case

class MyController:
    id = "my-controller-v1"
    def select(self, view):
        # Holding isolation can pass electrical checks while failing
        # the minimum restored-service requirement.
        return next(c.action for c in view.candidates if c.action.id == "hold")

result = evaluate_case(PortableCase(), MyController())
print(result["electrical_pass"], result["service_pass"])
```

This interface supports alternative selection within the adapter's bounded action
space. Arbitrary multi-switch optimization requires extending action generation
and validating its constraints; it is not already implemented. Register a tested
controller in `CONTROLLERS` and extend the validated API ID literals to expose it
in the dashboard. Raw `evaluate_case` is a developer API; official saved runs
fingerprint bundled controller source. External plugin users must record their
own source identity if they build a different result writer.

## Independent feeder

`circuits/ieee13/IEEE13Nodeckt.dss` is the original EPRI model from the
[pinned OpenDSS mirror](https://github.com/tshort/OpenDSS/tree/5005c668a72d20775f4c2d060feebb2866ba1d38/Distrib/IEEETestCases/13Bus).
The source and EPRI BSD license were checked byte-for-byte against that revision.
The license and upstream student attribution are preserved. `provenance.json`
records source hashes and every adaptation.

`model.dss` removes the unused global line-code include, coordinate display and
automatic solve, using the source's documented alternate fixed regulator taps.
All referenced local matrix line codes, phase connections, load models,
transformers and capacitors remain. The original source is not executed with
arbitrary redirects. The solver receives bundled reviewed commands only.

Validation compares **29 phase-voltage magnitudes** with the Official Results
column of Table 13 in the [RPI-hosted thesis](https://sites.ecse.rpi.edu/~vanfrl/documents/mscthesis/2018_Marcelo_Thesis.pdf).
The predefined tolerance is 0.003 pu (0.3 percentage points), allowing the upstream
concentrated distributed-load approximation and corrected 2016 cable matrix.
This is approximate reference agreement, not exact IEEE result replication.
The ambiguous regulator-output bus naming in that table is excluded. Phase-angle,
fault-current and dynamic behavior agreement are not claimed.

The public check uses the corrected Official-column v2 dataset. The frozen
legacy experiments retain their earlier 692.3 target for reproducibility.
See [the source correction](REFERENCE_VALIDATION.md#published-targets-and-provenance).

The separate restoration variant adds:

| Change | Experimental value / purpose |
|---|---|
| `backup_633` | 633→671, three phases, mtx601, 1800 ft, assumed 650 A |
| `backup_rg` | rg60→675, three phases, mtx601, 3200 ft, assumed 500 A |
| Other line limits | 700 A for three-phase lines, 300 A otherwise; explicit assumptions, not published ampacities |
| Transformer limits | Original ratings; both windings and every phase checked |
| Voltage envelope | 0.90–1.10 pu on every energized phase; experimental, not a safety standard |
| Critical demand | Load 675a; experiment designation |
| Faults | Whole-line 632670 or 671692, both terminals locked open |
| Controls | Fixed pre-incident taps; capacitors remain passive and disconnected in source-isolated islands |
| Demo loading | 0.8× published loads to avoid a pre-existing transformer phase-current violation |

The healthy reference's phase voltages already exceed 1.05 pu. At higher demand,
the original XFM1 transformer can exceed a winding phase-current limit; the adapter
reports that pre-existing violation rather than concealing it. The benchmark
retains such cases. No protective coordination, single-phase fault isolation,
regulator motion, cable thermal dynamics, or utility feasibility claim is made.
Whole-line switching plus preserved phase assignments bounds the connectivity
assumption; unsupported arbitrary phase switching is rejected by the interface.

## Failed switch with delayed confirmation

`temporal.py` has an explicit event queue and separate commanded, physical and
confirmed state. Environment events precede commands at equal timestamps;
actuation occurs next; position feedback precedes a timeout at the same time.
Command time is 1 s and actuator time 2 s. Timeout is measured from command time.
Environmental faults/delays are hidden from both trackers. Actual actuator failure
leaves the OpenDSS tie open. A successful actuation changes the native circuit
and triggers a solve. Energy not served integrates the solved snapshot between
event times over the recorded horizon.
The final event determines that horizon. Delayed feedback can lengthen it, so
raw energy totals across unequal horizons are not an improvement metric. The
experiment's target and pass/fail verdict use switch state at the fixed command
timeout, not those energy totals.

The deliberately faulty `optimistic-v1` tracker equates a command with success.
`confirmed-v2` waits, reports unknown at timeout, and incorporates late position
feedback. The target failure is a false restoration claim **at the timeout**,
not a transient optimistic indication before an otherwise successful actuation.
The corrected tracker does not retry or repair the switch and cannot recover
the lost service; the result makes that clear.

Seeded search varies actuator failure, confirmation delay and an irrelevant
heartbeat. Each candidate is simulated. Reduction deletes events and decreases
delay while preserving the same false-success failure. The included case reduces
to failed closure plus 5 s feedback delay with a 5 s command timeout: feedback
arrives at t=7, after the t=6 timeout. At 4 s delay it arrives at t=6 and is
processed first, removing the target failure. Tests check this boundary and
successful actuation. This intentionally seeded state-machine defect tests the
distinction between issuing a command and confirming its execution.

## Commands and outcomes

```bash
gridsense regress --output var/regression.json
gridsense verify-run --file var/regression.json
gridsense regress --file var/regression.json --candidate hold-v1
gridsense regress --file experiments/examples/failure-search.json
gridsense validate-feeder --output var/ieee13-validation.json
gridsense temporal --seed 42 --budget 12 --output var/temporal.json
gridsense verify-run --file var/temporal.json
```

Exit 0 means completed/passing verification; exit 1 is a regression contract,
reference or replay mismatch; exit 2 is invalid/incompatible input. Temporal
search exit 0 means the search completed, not that the faulty tracker is safe.
Its status reports a hit or no hit. Preserve original export bytes for checksum
verification. Parsed-and-rewritten JSON can change `1.0` to `1` and is not the
original exported record.

## Controller fault-injection study

The headless fault-injection study tests deliberately defective selectors and
message-only status trackers. It uses fixed case families, records which defects
are detected, and simplifies failing cases for replay. Experimental selectors
are separate from the registered dashboard controllers. [ASSURANCE.md](ASSURANCE.md)
reports all outcomes and computation costs.

The healthy voltage reference passes all 29 checks. The extended current, P/Q
and balance audit has four native-default mismatches. The dashboard labels the
voltage-only result so it cannot be mistaken for full physical-model validation.
