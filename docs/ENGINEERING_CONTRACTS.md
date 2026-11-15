# Engineering contracts

These are current implementation guarantees exercised by meaningful regressions.
They define the boundaries to preserve when maintaining the system.

## Bounded native work

FastAPI uses two simulation workers. `compute_in_pool` releases capacity when the
underlying future finishes, including after a caller disconnects. Cancellation
must not create extra unbounded native work. Each worker exits after its bounded
job to release contexts retained by the native wrapper. Queue saturation returns
an explicit unavailable response; a broken pool changes readiness until restart.
`test_reliability.py` and `test_native_workers.py` cover these contracts.

## Validated input and honest outcomes

Pydantic validates public records, budgets, equipment and timing. CLI case files
must contain a JSON object; invalid input exits 2 before saving a default run.
Replay mismatch exits 1. Electrical feasibility, restored service, claimed status,
unknown measurements and computation exhaustion remain distinct outcomes.
`test_reliability.py`, `test_electrical.py` and `test_failure_search.py` cover them.

## Observation and evaluator boundary

Controllers receive delivered measurements and known device state. Hidden demand,
future repairs and private actuator settings remain evaluator inputs. The native
adapter checks actual consequences independently. The oracle/permutation references
have explicit shared assumptions and privileged information; they are not fair
information-matched competitors or independent physical measurements.

## Plans, confirmation and recovery

A plan must fit the remaining command allowance and solve budget. Every operation
and intermediate electrical state is checked. Pending feedback blocks another
command; commanded, physical and confirmed positions are separate. Correlated
feedback at the deadline is processed before timeout. Repair makes a device
available; it does not reconnect it. `test_restoration_sessions.py` and
`test_execution_planning.py` cover sequences, bounds, faults and energy accounting.

## Atomic state and idempotent requests

Session checkpoint, frames, action and receipt commit together. A lost response
can be retried without duplicating the mutation. Conflicting revisions refresh
client state. Startup pauses saved playback without advancing time. SQL failure
and abrupt termination tests check rollback/recovery, not just mocked responses.
See [storage](DATA_MODEL.md).

## Asynchronous UI state

Late presets cannot replace an imported case. Saved temporal runs restore their
actual settings. Cached data is visibly stale during a read failure; controls
stay blocked until state is reconciled. Dialogs retain uncertain requests for
safe retry, contain keyboard focus and return it on close. Browser regressions
exercise network order and focus while retaining real native calculations.

## Reproducible numerical evidence

Comparison rejects non-finite values and Boolean/numeric substitutions. Native
load allocations, constitutive behavior and served-demand credit have different
meanings. The constant-power and native-default reference configurations have
separate names and reported outcomes. [Reference validation](REFERENCE_VALIDATION.md).

## Maintained fixtures

Seeded controller variants test detection of real electrical/service regressions;
they are isolated from the production controller registry. Foreign-build records
verify strict compatibility rejection. Frozen discovery sources support accounting
of their own study. These fixtures have an ongoing testing/reproducibility role;
they are not alternate application entry points.
