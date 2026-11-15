# Walkthrough: live restoration and reproducible failures

Follow [SETUP.md](../SETUP.md), start `gridsense serve`, and open the dashboard.
Start in **Live Grid**. Create a nominal session, queue a `line:feed_a` outage,
and step once. Its loads lose supply and a switch command waits for confirmation.
Step again: the alternate route supplies the loads while the equipment incident
remains active. Queue a repair for that incident, then follow the separately checked
return to normal. The controller may wait for its replanning interval; repair is
not an immediate switching command.

Inspect an equipment row for physical state and received measurements. Expand an
alarm for the exact triggering values. Open **Incident analysis → Live session
timeline**, select an earlier tick and compare its recorded predictions with
physical consequences. Export the capture or strictly replay the saved session.
The [dashboard guide](LIVE_DASHBOARD.md) describes failure cases and request recovery.

For the snapshot experiment below, choose **Incident analysis → Restoration lab**.
Here the supplied fault is already isolated. Demand readings are scenario inputs;
voltages, currents, and actual load powers come from OpenDSS.

## Compare prediction and consequence

Keep **Stale reading** selected and run restoration. Inspect **Nominal**, then
**Guarded**. They receive the same observations. Nominal uses received demand;
guarded also checks the lower and upper demand assumptions.

Click **Decision evidence** in the restoration result and expand **Show raw records**. Compare reading value,
timestamp and age with candidate predictions and actual loading. The default
nominal west route overloads the incoming west line; guarded chooses the east
route. Selecting a policy view inspects a recorded branch.

## Trace the code

| Step | Source |
| --- | --- |
| Validate the scenario | `backend/gridsense/domain.py`, `api.py` |
| Build observations and separate hidden demand | `service.py`: `observations`, `evaluate` |
| Generate and rank switching alternatives | `planning.py` |
| Apply operations and solve the native circuit | `electrical.py` |
| Save the completed incident | `storage.py` |
| Display branches and raw evidence | `frontend/src/App.tsx`, `Topology.tsx` |

## Replay or evaluate a change

**Verify replay** reapplies recorded actions to the recorded initial state in
fresh native contexts, checking source and solver compatibility first.
**Test controller changes** imports the inputs into a portable case. Inspect
minimum restored and critical kW requirements under **Scenario JSON and service
requirements**, then compare controllers. Try
`hold-v1`: it can satisfy electrical limits yet fail the service requirement.
The original record stays intact when a new comparison is created.

## Inspect a seeded caching defect

```bash
python experiments/reproduce_assurance.py experiments/assurance_results/reproducers/cached-action.json
```

Inspect `priming_case`, `original_case`, `reduced_case`, `reduced.reference`,
`reduced.candidate`, and `trials`. A deliberately defective selector reuses the
west tie chosen for the priming observation. With west demand 1.15 times its base
and east demand 1.10 times its base, that route reaches about 101.9% loading.
Recomputing selects east at about 99.3%. Both selectors face the same checks.

The reducer removes input deviations while preserving the failure category.
Failed simplification attempts remain in the record. This seeded selector is
available only to the headless study, separately from the live registry.

## Check confirmation and reference scope

Run **Controller tests → Switch confirmation**. Compare command, physical position,
received feedback, and timeout. The confirmed tracker may report unknown while
awaiting feedback.

**Controller tests → Failure search** finds and simplifies failing cases.
A search uses **Simplification checks** for its separate reduction budget. **Open
simplified incident** opens the smaller case in the separate snapshot lab; it does not mutate the
selected live session.

**IEEE feeder check** compares 29 voltage magnitudes. The extended headless audit
also retains four current/power mismatches; [ASSURANCE.md](ASSURANCE.md) explains
the load-model fallback and convergence diagnostics.

## Test another selector

```bash
python examples/custom_controller.py
```

The example demonstrates `select(view)` and an unmet service contract. A selector
uses the permitted view and advertised actions; the evaluator applies
electrical and service checks. [DEVELOPMENT.md](../DEVELOPMENT.md) covers regression
tests and source-version handling.
