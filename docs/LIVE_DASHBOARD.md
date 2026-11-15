# Live dashboard

Start the local service using [SETUP.md](../SETUP.md). **Live Grid** is the main
screen. The browser reads committed session state and submits backend actions;
it does not solve the circuit, advance a local simulation clock, or infer repair
completion from a countdown.

## Start and operate

Create a session with a title, **Session duration (s)**, initial feeder demand and
restoration policy. The duration is the backend's fixed `horizon_s`. After creation,
use **New session** to open the setup form again. The starting equipment is available; high demand can still violate
electrical limits. The dashboard selects nominal control explicitly. The API/CLI
default remains off. Guarded control samples uncertainty and may restore less
demand at greater computational cost. Settings are fixed for the session.

**Step one second** requests one committed logical tick. **Play session** and
**Pause session** control server pacing. Playback offers 1×, 5× and 10×; these are
requested rates, not real-time guarantees. A slow native solve delays playback
without skipping ticks. A completed horizon cannot be extended. Choose or create
another session to continue experimentation.

Changing views or closing the page does not pause a running server session.
Pause explicitly. A server restart leaves sessions paused, without simulating
elapsed wall time. The browser remembers the selected session when local storage
is available. The selector lists up to 100 recent sessions.

## Introduce disturbances and repair

Pause and click **Add disturbance** to open the event form. New events are queued for the next tick;
**Schedule disturbance** does not execute them immediately.

| Control | Meaning |
| --- | --- |
| Equipment outage | Whole line, transformer or source becomes unavailable and isolated |
| Demand change | Changes one feeder's requested demand factor; OpenDSS computes the consequence |
| Measurement delivery | Delays or drops newly sampled rows for the selected equipment |
| Switch response and confirmation | Changes switching delay/failure and command-confirmation delay/drop |
| Schedule simulated repair | Queues availability recovery after the chosen simulated delay |
| Schedule repair for an active incident | Queues repair completion for the next tick |

The form closes after an accepted submission. Closing it without submitting changes
no session state. Expand **Scheduled events** in that form to inspect the queue.
The displayed queue is simulator input, not information passed to the controller.
At most two equipment incidents can overlap. Invalid combinations, events beyond
the horizon, or obsolete revisions are rejected with the server's explanation.
There is no queue-edit or cancel control; inspect scheduled events before stepping.

Repair changes availability only. An isolated transformer may remain disconnected,
and healthy MV voltage cannot supply its LV group. With control off, no automatic
reconnection occurs. With control enabled, return to normal requires a checked
sequence, confirmed positions and received supply evidence. Switching can briefly
interrupt service. Repair seconds are demonstration settings, not field estimates.

Expand **Planning assumptions** when creating a session to set the controller's
assumed actuation/confirmation times and energy window. The confirmation timeout
must cover those waits. These settings are separate from scenario switch-response
disturbances; actual commands still need position feedback.

## Read the evidence

The topology and four electrical metrics show the **simulated physical state**
from the latest committed native solve. Each group shows its MV bus, distribution
transformer and aggregate load. Source and main transformer are shown separately.
Open lines and isolated equipment use text and dashed treatment as well as color.
Selecting a node or line opens an equipment drawer. **Inspect equipment** opens
the same drawer with a selector for every asset. Close it with the close button
or Escape; keyboard focus returns to the control that opened it.

The **Served demand** metric uses delivered active power, capped at requested demand
for each energized load. Equipment inspection also shows the uncapped OpenDSS
terminal power and the controller's demand estimate; these are distinct quantities.

Equipment inspection separates physical position/availability/native results from
**received measurements**. Rows identify the sensor, sequence, value, unit,
measurement/receipt times, age, quality and source. Device-status rows are modeled
messages. Demand estimates are held when supply is absent; requested demand is
not silently substituted for a missing meter reading.

**Restoration status** uses received information. It can lag behind physical truth
or report insufficient information. **Switch commands** separately report pending,
confirmed, failed, late or unknown outcomes. Seeing alternate supply does not imply
that the command receipt arrived or that damaged equipment was repaired.

The main screen keeps supply status, active alarm count, stale or invalid row
counts, equipment awaiting repair and electrical violations visible. **View alarms**,
**Switch commands** and **Restoration decision** open an incident panel from
the status area beside the topology. These are live details, not a captured historical record.

In that panel, expand an alarm to see its rule, threshold, reset value, and the readings that
raised or cleared it. A voltage or loading rule explains a condition, not its physical
cause. Expand a restoration decision to inspect all evaluated alternatives,
predicted service/loading, uncertainty samples, structural refusals, exact inputs
the declared timing, predicted critical/total unserved energy and the evaluation
budget. Fresh overload evidence shows the received device loading, its measurement
time and limit. Remembered load-set restrictions are explained with the alternatives.
Predicted energy uses held estimates; actual session energy comes from physical frames.
The selected plan is best among the alternatives checked within the search budget.
It may miss a better plan or a violation between the sampled demand values. Saved
plans without timing or energy metadata show those values as not recorded; the
viewer does not infer them. Advancing or strictly replaying a session still
requires its recorded source and native versions.

Optional line motion marks energized, loaded connections while playing. It does
not measure propagation speed or power magnitude. Reduced-motion preferences
disable that animation. Nodes are keyboard selectable; the equipment selector
provides an alternative to diagram navigation. Tables scroll within their panels.

Use **View** above the diagram to focus on the source or one bus, transformer and
load group. This enlarges its readings without changing the simulated grid.
**Show whole grid** returns to the overview. The focused group stays selected as
measurements update or the screen size changes; choosing another saved session
resets the diagram to the overview. The full network is small on a phone, so use
the group view or equipment inspection for individual readings.

On phones, the analysis and controller menus wrap into rows so every tool remains
visible. Scenario presets also wrap rather than clipping a choice. The Restoration
lab refits its whole diagram when the canvas changes size; zoom remains available
for individual readings.

## Incident analysis and controller tests

**Incident analysis → Live session timeline** captures the selected session through
a stated tick/revision. It does not move forward while being inspected. Refresh
explicitly to obtain newer history. Choose a tick to inspect physical changes,
actuation, received alarm evidence, confirmation and the recorded plan. Select
**Decision**, **Commands**, **Alarms** or **Raw record** for that tick rather than
reading all four sections at once. Energy
totals integrate known intervals; unknown intervals and the final zero-duration
snapshot are disclosed.

**Refresh timeline** loads a newer capture. **Export captured session** downloads
exactly the displayed record. **Check session replay** asks the server to capture
and regenerate its current saved session;
the result identifies the replayed horizon. It may be newer than an earlier analysis
capture. Pause before replay. No result is inferred from a successful download.

Use **Restoration lab** to compare snapshot decisions. Its result has a **Decision
evidence** button for the inputs and outcomes; evidence is not a separate navigation
item. Expand **Demand sweep** to test fixed observations against changing demand.
Use **Incident archive** to reopen saved cases.
These experiments do not change a live session. **Controller tests** offers
**Controller comparison**, **Switch confirmation**, **IEEE feeder check** and
**Failure search** in one navigation row. Failure search looks for violations,
simplifies a case and checks its replay. [WALKTHROUGH.md](WALKTHROUGH.md) traces those tools.

## Conflicts and uncertain requests

Every action carries the displayed revision and a new request ID. Another tab
or playback tick can win the race; a rejected stale action refreshes the view and
requires an explicit new submission. No hidden retry advances the clock.

If a response is lost or unreadable, the browser cannot tell whether the action
was saved. It blocks further actions and keeps the original request ID and payload.
**Retry same request** recovers its receipt without executing it twice. When local
storage works this pending request survives page reload. If storage is unavailable,
the UI reports that limitation; keep the tab open to resolve the request.

Errors and **Retry same request** remain available inside an open panel. If a
retried request was accepted, the panel closes after its receipt is recovered.

Read failures label the last visible tick and block controls until a successful
refresh. Solver errors are unknown electrical states. Server worker saturation,
validation errors and revision conflicts remain visible. The top-bar readiness
indicator describes the initial connection check; the live error banner describes
later session-read failures. This remains a local, single-user simulator.
