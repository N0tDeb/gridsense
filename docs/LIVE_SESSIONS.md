# Live teaching-feeder sessions

A session starts with a healthy balanced feeder and runs real OpenDSS power flow
at integer simulated seconds. The API and CLI support physical outage/repair
events, demand changes, delayed or dropped measurements, rule alarms, bounded
restoration, confirmed switching, persistence and strict replay. The dashboard's
[Live Grid](LIVE_DASHBOARD.md) uses the same session API; the snapshot restoration
lab compares isolated snapshots. Automatic session control defaults to off
in API/CLI configurations; set `control.policy` to `nominal` or `guarded` to enable
it. The browser selects nominal control for a new session.

## Run an episode

From the installed project root:

```bash
python examples/live_episode.py
gridsense episode --config examples/live_episode.json --output var/live-episode.json
gridsense replay-episode --file var/live-episode.json
python examples/restoration_episode.py
```

The example isolates `tx_a1` at second 2 and records repair completion at second 5.
Its equipment status is delayed by two seconds. Load-supply status has its own
delivery settings, so the two reports need not arrive together. After repair the
transformer is available but still isolated; its 400 kW load remains unserved.
An MV tie cannot bypass that transformer. The example uses a temporary database;
the `episode` CLI stores its session in `--data-dir` (default `var`).

On Windows, replace `gridsense` with `.\.venv\Scripts\python.exe -m gridsense.cli`
and `python` with `.\.venv\Scripts\python.exe`; see [setup](../SETUP.md).

## Clock and physical events

Creation solves and samples time 0. A step advances exactly one simulated second:

1. Apply all due repair completions, then the other due events in their recorded
   sequence. Only the named incident clears. A same-time new incident remains active.
2. Attempt due switch actuation, respecting equipment availability and radiality.
   Solve the resulting physical state once with OpenDSS, including any actual
   voltage or loading violation.
3. Sample on the configured interval and enqueue samples with their delivery times.
4. Deliver due rows in deadline/sequence order, rejecting duplicates or older readings.
5. Deliver correlated command feedback before evaluating timeouts. Feedback at
   the deadline wins; duplicate, wrong-device and pre-command rows cannot confirm.
6. Update demand estimates and alarms, then plan, revalidate or issue one command
   from received information. New commands cannot actuate until the next tick.

A repair changes availability, not switch position or connectivity. Outages are
assumed whole-device trips, not simulations of fault currents or protection.
The model has no moving regulators, transient dynamics, or physical repair process.

| Event kind | Required fields besides `kind` and `at_s` |
| --- | --- |
| `outage` | Unique `incident_id`, `equipment_kind` (`line`, `transformer`, `source`), `equipment` |
| `repair` | An active `incident_id` |
| `demand` | `feeder` (`a`, `b`, `c`), `factor` (0.5–2) |
| `transport` | Qualified `equipment` ID, `latency_s` (0–30), optional `drop` |
| `actuator` | Qualified switchable `equipment` ID; optional `actuation_delay_s` (1–10), `fail`, `feedback_delay_s` (0–30), `drop_feedback`, `duplicates` (0–2), `duplicate_delay_s` (1–10) |

Examples of IDs are `line:feed_a`, `transformer:tx_a1`, `load:a1`, `bus:a1_lv`,
and `source:source`. Outage events use the unqualified equipment name. Transport
overrides affect samples taken from that event onward, not already queued rows.
Setting `drop` back to false resumes sampling delivery; dropped rows are not recovered.
Actuation delay is captured when a command is issued. Failure and feedback settings
are taken when it is executed. Duplicate feedback retains the original sample
sequence. These private scenario settings never enter the planning view.

Events must be strictly after the current tick and within the horizon. Validation
checks the full future timeline, including queued events and incident lifetimes.
Incident IDs cannot be reused. At most two equipment incidents may be active
after a timestamp is resolved; two incidents on the same device still count as two.
The horizon is 1–600 seconds and the queue holds at most 128 pending events.

## Measurements and evidence

Each row carries a sensor/equipment ID, quantity, unit, sequence, measurement time,
receipt time, source and quality. Native rows include minimum/maximum phase bus
voltage, maximum line current, primary/secondary transformer current, loading,
load P/Q and source P/Q. These are phase aggregates, not waveforms.
Availability and position are explicitly labeled modeled device status.

The default sample interval is one second, delay zero, and freshness limit two
seconds from measurement time. Invalid or deenergized numerical rows cannot be
treated as healthy readings. Nonconvergence/native solve failure records unknown
electrical measurements and pauses playback; it never invents zero demand.
Programming or storage failures roll back the whole tick. Unexpected playback
worker failures are logged and trigger a pause where storage is still available.

Demand estimates require received native load power, an energized indication,
and matching-time LV voltages within the teaching model's constant-PQ window
(0.8–1.2 pu). The operating voltage limits remain 0.95–1.05 pu; a voltage alarm
does not discard an otherwise usable received power estimate. Outside the model
window, or when these rows are unavailable,
the last valid estimate is held. With no valid prior estimate, demand is unknown.
Disconnected zero power does not overwrite a held estimate. The default bounds
start at ±10%, grow by two percentage points per simulated second, and cap at
±80%. These settings are assumptions for experiments, not statistical confidence.

Numerical alarms default to two fresh violating samples to raise and three
fresh healthy samples to clear. Voltage limits are 0.95/1.05 pu, with reset at
0.96/1.04 pu. Loading raises above 100% and clears at or below 98%. Equality at a
violation limit does not raise. An intervening invalid/stale observation resets
the evidence streak, and cannot clear an active alarm. Duplicate rows never
count as new evidence. Discrete unavailable/no-supply indications use one fresh
status row to raise or clear. Alarms retain raw trigger/clear rows, thresholds,
units and timestamps. A low-voltage alarm explains the measurement breach; it
does not claim to know the underlying fault cause.

## API and persistence

Run `gridsense serve`; interactive request schemas are at `http://127.0.0.1:8000/docs`.

| Route | Purpose |
| --- | --- |
| `POST /api/sessions` | Create with `request_id` and optional `config` |
| `GET /api/sessions` | Up to 100 most recent session summaries |
| `GET /api/sessions/{id}` | Clock/revision, received rows/estimates/alarms and public control state/settings |
| `GET /api/sessions/{id}/simulation` | Additional evaluator-only physical state, electrical result and future events |
| `POST /api/sessions/{id}/actions` | `step`, `play`, `pause`, `rate`, or `schedule` |
| `GET /api/sessions/{id}/export` | Full definition, actions, frames, final checkpoint and checksum |
| `POST /api/sessions/{id}/replay` | Strict regeneration and comparison |

For example, create with `{"request_id":"demo","config":{"horizon_s":10}}`.
Use the returned ID, then send an action such as
`{"request_id":"step-1","expected_revision":0,"operation":"step"}`.
Each successful mutation returns a new revision. Retrying the identical request
returns its original receipt. Reusing its ID with a different payload or sending
a stale revision returns 409. Fetch the current state before issuing a new action.
Request IDs contain 1–80 letters, digits, underscores or hyphens.

`step` requires a paused session. `play` accepts optional `rate` 1, 5 or 10;
`rate` changes pacing only. `schedule` accepts a nonempty `events` list. At most
four sessions may play. There is one pacing loop per server: run one local
server process. Native worker startup and serialized database writes mean the
requested speed is not a real-time guarantee. Slow ticks are never skipped and
never followed by a burst to catch up with wall time.

The checkpoint, frame and action receipt commit in one SQLite write transaction.
Cancellation of an HTTP wait does not cancel its worker's transaction. A restart
records a pause at the last committed time; it performs no wall-time catch-up.
These guarantees concern the local SQLite session history, not distributed jobs
or external field equipment.

## Planning and confirmed commands

The controller requires fresh availability/position rows for every switchable
device and a positive valid prior demand estimate for every load group. Unknown
or inconsistent information produces an explicit refusal. Received device pairs
must have matching timestamps; different devices can have different fresh ages.
The planner uses each group's held native kW estimate and the declared fixed
power factor. It never reads actual demand factors, future repairs or actuator
failure settings. Prediction is marked separately from the physical result.

The nominal policy tests the received estimates. Guarded tests up to 15 distinct
points: nominal, each of six groups at its lower and upper bound, and joint
all-low/all-high. These are finite stress samples, not confidence levels or a
proof across the whole uncertainty box. Rejected candidates stop at their first
violating sample; reports record checked and required sample counts.

The planner checks expected switching and confirmation times, widening guarded
bounds without assuming future measurement refresh. It compares ordered paths
using terminal critical supply, then predicted critical and total unserved energy
over the same window, terminal total supply, operation count and peak tested
loading. Break-before-make interruption is charged in that energy calculation.
The [execution planning guide](EXECUTION_PLANNING.md) defines the timing, objective,
cache, pruning and sampled-check limits.

Search includes hold, modeled line toggles, distribution-transformer disconnects
for load shedding, and closure of available isolated transformers/source. It
retains different switching orders, with no repeated device in one plan. Every
resulting step must pass native voltage, line/winding loading and convergence
checks. An infeasible initial state may be left by a checked corrective operation.
Graph service bounds only prune choices that cannot outrank a checked candidate;
they never establish electrical feasibility.

Fresh synchronized overload evidence requires a first switch that reduces the
load exposure of affected devices. Remembered overloaded load combinations stay
blocked while their associated received demand estimates are unchanged. Changing
unrelated equipment cannot bypass that check. This restriction is conservative;
it can retain partial service when isolated loads cannot provide new measurements.

Guarded bounds enter the decision signature at 0.001 kW precision; received means
use 1 kW rounding. A timestamp alone is not a trigger. Shrinking energy windows
can trigger reconsideration for either policy. The ordinary two-second cooldown
still applies to those changes. Newly observed faults, repairs and overload changes
supersede that cooldown. Pending confirmation and command/decision caps still apply.

The default three-operation, 2,048-native-call budget is shared by sequence
revalidation and replanning. Exact native results are reused only within a decision.
An exhausted budget is explicit, and unchecked alternatives remain unknown.
Results are best among completed checked bounded plans, not globally optimal
restoration. Future demand changes can still cause violations; the
[measurement-refresh study](MEASUREMENT_REFRESH.md) records incomplete restoration
as well as its consequences.

The operation bound also respects the episode's remaining command allowance.
For example, one remaining command cannot start a two-command return from a tie
to the normal feeder. The controller holds the supplied configuration when it
cannot finish that sequence. This check does not guarantee completion if later
feedback is lost, an actuator fails, or new measurements invalidate the plan.

Only one command may await confirmation. A position receipt proves the reported
switch position; fresh native load power, energized status, LV voltages and equipment
loading establish the separate supply status. Status rows can still lag within
the configured freshness window. No status label claims physical repair.

The default confirmation deadline is five simulated seconds. Timeout marks the
outcome unknown and blocks further switching, even if general telemetry reports
the intended position. A later correlated receipt resolves uncertainty and forces
a fresh decision. Failed actuation cancels the remaining plan. After a timely
confirmation, the remaining sequence is checked again using current received data;
position rows older than that confirmation must first catch up. The defaults allow
two attempts per requested device position, 24 commands and 32 decisions per episode.
Limits produce a stated stop rather than endless retries.

An observed repair requests return to the normal configuration when all observed
outages have cleared. This is a separate operating preference: extra switching can
be justified by normal operation, not by the minimum-switch restoration objective.
All recovery intermediates must be feasible and terminal critical/total service
must not fall below holding service. A blocked recovery holds the backup route.
Break-before-make can temporarily shed demand; that interruption is recorded.
Received electrical violations take priority over returning to normal: corrective
reconfiguration or shedding is attempted first, with the recovery request retained.

Physical actuation enforces availability and the radial interlock, but never uses
hidden true demand to reject an otherwise permitted command. If stale information
causes an overload, the result remains in the physical record. Fresh sustained
alarm evidence can mark a configuration unsafe; it is excluded until rounded
received demand changes. New delivered demand, status, alarms or confirmation can
trigger replanning. Aging uncertainty alone does not cause a repeated hold decision;
remaining commands always receive a fresh feasibility check.

## Fixed-horizon outcomes

Each interval `[t-1,t)` uses its previous native result. The final sample has zero
energy duration. Metrics record raw and whole-state-feasible served kWh, critical
service, unserved kWh, violation snapshots, unknown intervals, actuator attempts,
actual position changes and first full compliant recovery delay. Feasible service
is zero for a globally violating state; it does not mean every individual supplied
load was unsafe. Unknown intervals count as neither known service nor known unmet
demand. Wall-clock cost is measured by the experiment runner, outside replay data.

See [the session comparison](SESSION_EVALUATION.md) for complete cases and limits.

## Replay and interpretation

The export pins session source, model bytes, native solver identity, event order
and schema. There is no random noise, so its manifest explicitly records no RNG
seed. Replay reconstructs time 0 and every committed logical action, then compares
all frames and the final state, including queued samples, actuation, confirmation,
alarms, controller state and energy metrics. Numerical
comparison uses relative tolerance `1e-7` with a unit absolute floor. Foreign
source/model/solver identities are rejected. A checksum detects accidental edits;
it is not a cryptographic signature or proof that input scenarios are realistic.

The ordinary observation view excludes hidden demand, incident causes and future
events. Rules use that view's delivered rows. Simulation endpoints and exports
are privileged evaluation views by convention, not authenticated resources.
Keep them out of controller inputs when extending the system.
