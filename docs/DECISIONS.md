# Engineering decisions

| Decision | Reason | Trade-off |
| --- | --- | --- |
| Native OpenDSS contexts per simulation | Switching must be checked against solved voltage, current, and power | Native versions and model assumptions must be reproducible |
| Separate equipment availability and isolation | Repair must not silently reconnect equipment or clear another incident | The whole-equipment trip is an explicit simulation assumption |
| Distinct native power and served-demand credit | Capped service must not corrupt physical P/Q balance | Consumers must choose the quantity appropriate to their question |
| Separate model-aware reference configuration | Explain native load-law behavior without erasing failed PQ comparisons | Conditional envelopes and internal checks do not establish field validation |
| Graph candidates plus electrical feasibility | Connectivity identifies possible routes; solving establishes constraints | Search remains bounded to advertised switching actions |
| Separate observations from evaluator truth | Stale readings should influence decisions without leaking hidden demand | Inputs must record both received readings and actual state |
| Nominal and three-sample guarded snapshot policies | Inspectable policies expose safety/service trade-offs | Sampling provides no continuous uncertainty guarantee |
| Electrical and service contracts | Holding isolation can be electrically acceptable while restoring no service | Each case must state useful restoration requirements |
| Immutable records and strict fingerprints | Replay identifies the original source and native solver | Formatting also creates a new replay version |
| Separate current-code regression | A saved case remains useful after a controller changes | It creates a new evaluation with historical provenance |
| SQLite, FastAPI, and a bounded process pool | Durable local records and native work outside the event loop | One local server; snapshot jobs are not resumable |
| Transactional session ticks and request IDs | Clock, observations and action history must agree after retries or restart | Native work holds the SQLite writer; playback can run slower than its target |
| Received rows and explicit rule evidence | Alarms must show values, limits and fresh supporting samples | Rules explain limit breaches, not physical fault causes |
| Repair completion without automatic closure | Available equipment still needs a deliberate reconnection decision | Checked return to normal may temporarily interrupt service |
| Bounded session planning and finite six-group demand samples | Check every intermediate state from received evidence within a fixed solve budget | Guarded plans can cost more and supply less; no global or continuous guarantee |
| Public switching assumptions and future bound checks | A received estimate can age while commands wait; physical event settings stay private | Finite time/demand points and assumed response times do not guarantee future safety |
| Common-window unserved-energy comparison | Different switching orders can interrupt supply for different durations | Held nominal demand and successful switching are assumptions; terminal critical supply has priority |
| Exact native caching and objective-bound pruning | Reuse identical native problems and skip paths unable to beat checked choices | No reuse across decisions; graph bounds cannot certify feasibility |
| Distribution-transformer disconnects | Shed a load group without opening its whole MV feeder | Remote commandability and switching suitability are teaching assumptions |
| Remembered overloaded load sets | Changing unrelated equipment must not bypass received unsafe evidence | Conservative rejection can retain partial service until relevant estimates change |
| One correlated command at a time | Missing confirmation must not silently become a successful switch | Lost feedback can block further recovery even when supply is observed |
| Browser as a session client | One backend owns time and commits; topology shows returned native state | Playback continues when a tab closes; explicit pause is required |
| Captured analysis separate from live operation | A historical tick must not move while being inspected | Refresh analysis explicitly; replay reports its own captured horizon |
| Retain uncertain client request IDs | Recover a lost receipt without duplicating a committed mutation | New controls remain blocked until the request is resolved |
| Separate permutation reference | Check production candidate construction and ranking | The reference still shares the native physics and sample definition |
| Separate experimental selectors | Seeded defects test the evaluator without entering the live registry | Results apply to the declared variants and cases |
| Preserve unfavorable results | Service loss, missed failures, and mismatches bound the claims | Results need interpretation beyond a single score |

## Scope

Live Grid follows a feeder from healthy operation through configured disturbances,
alarms, restoration and repair recovery. The backend controls the clock and waits
for switch confirmation. Incident analysis contains the recorded timeline and
snapshot lab. Controller tests contains regression, search and reference experiments.
The API and CLI expose the same session engine.
Fault-prediction ML, forecasting, learned trust, and composite health scores
would require separate data and evidence of decision benefit.

The dashboard keeps topology prominent, supplements color with text, and
separates restored service from repaired equipment. Predicted results and actual
simulated consequences remain distinguishable.

## Source fingerprints

Strict replay uses source bytes and solver identity. Formatting therefore changes
record compatibility as well as algorithm edits. Saved inputs can still be used
in a new regression; the resulting record identifies the new implementation and
retains its baseline. This is separate from reproducing the original run.
