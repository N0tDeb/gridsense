# Electrical models and assumptions

The teaching feeder supports healthy and isolated states, explicit equipment
availability, and steady-state switching checks. Live Grid follows the equipment
lifecycle; Restoration lab runs separate post-isolation snapshots. The separate
IEEE13 reference, experimental modifications and device-event assumptions are in
[CONTROLLER_TESTING.md](CONTROLLER_TESTING.md).

## Included feeder

The feeder definition is `gs-six-load-v1`. It is a custom balanced
three-phase teaching circuit, not an independently validated utility model or
an IEEE test feeder. Ratings are chosen to produce inspectable restoration
trade-offs and must not be mistaken for field-derived values.

- A 33 kV source supplies a 6 MVA, 33/11 kV delta/wye transformer.
- Three 11 kV feeders each supply two balanced loads through individual
  11/0.415 kV delta/wye transformers.
- In Restoration lab's incident experiments, `feed_a` is already isolated at both
  ends. `healthy_state()` instead closes the normal feeder lines with no lockouts.
- `seg_a` can disconnect noncritical residential demand while retaining the
  medical-campus demand point.
- Normally open MV ties connect the healthy west/east district bus to `a1`.
  All ties connect the same voltage level and phase arrangement.

Line positive-sequence impedance is 0.18 + j0.20 ohm/km; zero-sequence impedance
is 0.45 + j0.40 ohm/km. Shunt capacitance is zero in this small model. Demand is
balanced constant power at 0.95 power factor, with the DSS voltage-dependent
fallback outside the configured load-model range (0.8–1.2 pu in this feeder).
The teaching solver uses a convergence tolerance of `1e-8`; this numerical setting
does not change the load law or the operating voltage limits.

Loads disconnected from the source are explicitly disabled in the electrical
solve to avoid zero-voltage island constant-power equations. Their requested
demand remains in the unserved accounting. They are not reported as healthy
simply because disabled loads disappear from the power flow.

## Equipment state and accounting

An equipment outage has an incident ID, an asset kind, and an asset ID. The
`isolate_outage()` helper applies the declared whole-equipment trip: it opens
both native line or transformer terminals, or disconnects the source. This is
an availability and isolation assumption, not a short-circuit calculation or
fault-localization algorithm. Unavailable equipment cannot be reconnected.

`repair_outage()` removes only the named incident. It leaves switch positions
unchanged, and another active incident on the same asset still blocks reconnection.
Repair completion is a supplied simulation input, not inferred from measurements.
The headless [equipment example](../examples/equipment_availability.py) separately
solves outage, alternate MV routing, repair, reconnection, and normal topology.
The [live-session API and CLI](LIVE_SESSIONS.md) and [Live Grid](LIVE_DASHBOARD.md)
schedule these outage and repair events on an integer-second clock. An event
does not reconnect equipment. Optional control plans and confirms separate
reconnection commands using received observations.

An energized MV bus does not imply supplied LV demand. A failed distribution
transformer leaves its load unserved even if an MV tie energizes its upstream bus;
the model has no alternate LV connection. Main-transformer or source isolation
removes supply from all load groups.

Each solved result separates:

- **Requested demand:** the scenario's nominal active-power requirement.
- **Native load P/Q:** uncapped powers measured at OpenDSS load terminals.
- **Served demand:** native active power, capped between zero and requested kW.
- **Voltage-compliant served demand:** served kW at connected LV load groups whose
  phase voltages meet the operating envelope. This is not a thermal-feasibility score.
- **Power balance:** native source P/Q minus uncapped load P/Q and network losses.
- **Restored demand:** service gained by the explicitly named incident loads,
  relative to `restoration_baseline_kw`. Snapshot adapters assign zero baselines
  to the loads disconnected in their initial incident state. A generic solve has
  an empty baseline and earns no incident restoration credit. This field is not
  net system service gain: shedding elsewhere must be assessed through total
  served/unserved demand and the complete switching sequence.

The native accounting fields are null when the solver does not converge;
load rows also carry `quality="unconverged"`. Snapshot fields may still contain
values, but `converged=false` and `feasible=false` invalidate the result.
Consumers must check these flags before using voltage, loading, or service values.
The IEEE adapter explicitly rejects the equipment-state options. Its aggregate
native-accounting fields remain null rather than implying measured zero power;
individual load rows retain uncapped native P/Q and solve quality.

IEEE load voltage comes from its connected native conductors. Wye rows report
phase-to-neutral voltage; delta rows use the complex phase-to-phase difference.
`voltage_pu` is the minimum of that load's branches on the bus voltage base, with
the branch values and maximum also retained. `bus_min_voltage_pu` is a separate
bus-wide quantity. The row also records voltage on the load's own rated base;
these bases can differ slightly. Native load-law transitions use the load base.
The adapter's feasibility envelope still checks energized bus phases at 0.90–1.10
pu. These reporting changes do not redefine the frozen native-default reference.

## Feasibility

- Graph remains a forest (radial operation).
- No locked-open line may be closed.
- No unavailable line, transformer, or source may be connected.
- OpenDSS must converge.
- Every energized source/distribution/load-bus phase must lie within 0.95–1.05 pu.
- Every closed line must remain at or below its configured continuous current rating.
- Both transformer winding phase currents must remain at or below rated current.
- Each intermediate switching state must pass the applicable checks.

Energized-bus voltage excludes intentionally dead buses. Demand at a dead bus is
instead counted as unserved. A path can restore real power and still be rejected
for excessive line or transformer loading or out-of-range voltage.

These checks do not model protection coordination, short-circuit duty after
reconfiguration, cold-load pickup, motor dynamics, synchronization, switching
transients, thermal time constants or crew operation. Live sessions separately
represent supplied device failures and integer-second command/repair delays;
those delays are not field-derived restoration times. “Feasible” means feasible
within this declared steady-state model.

## Demand observations

The snapshot experiment accepts an exact scenario demand factor for A and C, and a reported
factor for B. Demand inputs are synthetic estimates/telemetry assumptions, not
OpenDSS current measurements or utility SCADA records. A's requested demand is
assumed known even while its actual served power is zero after isolation.

Only B is stale in the snapshot experiment. An age of zero requires reported B to equal
actual B. A positive age permits a different historical reading. Age itself does
not statistically determine error; the ± uncertainty percentage is a separately
declared user assumption. A and C have exact known demand within this experiment.

The guarded policy checks B at reported × (1−u), reported, reported × (1+u).
It does not prove monotonicity or certify all intermediate values. The actual B
factor may lie outside that interval; such failures are kept in the evaluation.

Live sessions instead sample native P/Q, bus voltages, equipment loading and
status at configured times. Any equipment's samples can be delayed or dropped.
The demand estimate uses received power with matching-time LV voltage inside the
native constant-PQ window (0.8–1.2 pu), while operating limits remain 0.95–1.05 pu. It
holds the last valid value during interruption. Unknown/held demand is not
replaced with hidden scenario truth. The snapshot planner uses its own scenario inputs rather than these session estimates. [LIVE_SESSIONS.md](LIVE_SESSIONS.md) defines the separate
sensor, freshness, alarm and uncertainty assumptions.

## Objectives and terminology

The snapshot policy ranks feasible candidates by critical kW first, then total
served kW, then fewer operations, then lower maximum equipment loading. kW values are rounded to 0.1 for ranking to reduce numerical sensitivity.
Values near a rounding boundary can still change the selected route; the observed
case and its trade-off are recorded in [EVALUATION.md](EVALUATION.md).
Critical priority is a scenario choice.

The snapshot candidate space includes at most one tie closure and one prior
affected section opening. It excludes arbitrary multi-tie switching optimization.
The separate live planner checks bounded sequences of up to three operations,
including recovery to normal; [LIVE_SESSIONS.md](LIVE_SESSIONS.md) defines its
confirmation rules, uncertainty samples and native-solve budget. Live ranking
prioritizes terminal critical supply, then critical and total unserved energy over
the same declared window, terminal total supply, fewer operations and lower peak
tested loading. [EXECUTION_PLANNING.md](EXECUTION_PLANNING.md) specifies the timing,
future checks, conservative overload restrictions and prediction limits.

- **Restored:** demand is served through the selected alternate path.
- **Isolated:** the faulted section remains open at both ends.
- **Repaired:** a named outage has been cleared by a supplied completion event;
  isolation remains until a separate reconnection. The dashboard's snapshot
  experiment does not perform this lifecycle.
- **Replay:** deterministic reconstruction and reapplication of recorded actions.
- **Reference:** best feasible option in this bounded set with true demand.

## Reference categories

The public healthy voltage check uses the corrected Official-column v2
dataset. The frozen v1 comparators below retain the legacy voltage dataset.
[Correction and source identity](REFERENCE_VALIDATION.md#published-targets-and-provenance).

The frozen original IEEE comparator retains its four native-default mismatches.
The separately named `ieee13-native-model-envelope-v1` configuration keeps the
same native circuit and load voltage thresholds, but solves at `1e-8` tolerance.
It distinguishes 29 independently published voltage comparisons, 42 declared
load-property checks, 24 conditional power/current envelopes, and two internal
power balances. The envelopes use published voltage ±0.003 pu and the declared
load law; they are not independent measured current or power observations.
The convergence study varies tolerance and demand and records iterations and
solve time. See [ASSURANCE.md](ASSURANCE.md) for provenance and interpretation.
