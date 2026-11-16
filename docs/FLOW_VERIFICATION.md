# Feature and flow verification

This report answers whether the project works through complete user journeys,
including bad inputs, interruption and recovery. Coverage is based on real
native OpenDSS execution, API/backend checks, Chromium journeys and strict replay.
It is a coverage map, not a guarantee for every possible input or platform.

The verification procedure and platform scopes are in
[VERIFICATION.md](VERIFICATION.md). The latest executed counts and logs are
available in the [GitHub Actions run artifacts](https://github.com/N0tDeb/gridsense/actions/workflows/checks.yml).

| Area | Journeys checked | Main evidence |
| --- | --- | --- |
| Startup | Native readiness; frontend/API health; unavailable startup; readiness changes without advancing time | `readiness.spec.ts`, `test_native_workers.py`, runtime record |
| Live controls | New/saved sessions; pause, step, play; horizon stop; pause-before-step; reload | `live.spec.ts`, `test_session_api.py` |
| Outage and recovery | Healthy → isolation → confirmed backup → repair → checked return to normal | `live.spec.ts`, `test_restoration_sessions.py`, runtime record |
| Equipment availability | Transformer/source outages; repair separated from reconnection; overlapping incidents and refault | `test_equipment.py`, `test_episodes.py`, `live.spec.ts` |
| Controller decisions | Nominal/guarded/off; critical partial service; stale overload; time-aware plans; intermediate checks and budgets | `live.spec.ts`, `test_execution_planning.py`, `test_restoration_sessions.py` |
| Measurements and alarms | Native raw rows; phase/branch mapping; stale/dropped/out-of-order samples; unknown failed solves; alarm raise/clear evidence | `live.spec.ts`, `test_episodes.py`, `test_audit_regressions.py` |
| Switch confirmation | Commanded/physical/confirmed positions; failed actuators; timeout boundary; delayed or lost feedback | `verification.spec.ts`, `test_restoration_sessions.py`, `test_verification.py` |
| Snapshot restoration lab | Real nominal/guarded comparisons; raw evidence; replay; review; invalid-input rejection | `workflow.spec.ts`, `test_api.py`, `test_electrical.py` |
| Sweep | Fixed-observation cases; real electrical outcomes; export round-trip | `workflow.spec.ts`, `test_api.py` |
| Archive | Persistence across reload/restart; search; reopening original evidence | `workflow.spec.ts`, `test_api.py`, `test_failure_search.py` |
| Controller tests | Service and electrical requirements; hold rejection; imported incident case; saved comparison; rerun against current controller | `verification.spec.ts`, `test_verification.py` |
| Public IEEE check | Corrected 29-value Official-column comparison; displayed 692.3 target; separate modified-feeder restoration | `verification.spec.ts`, `test_published_reference.py` |
| Failure search | Discover, reduce, reproduce, export and reopen; exhausted domain; inconsistent reference and no false safety claim | `failure-search.spec.ts`, `test_failure_search.py` |
| Temporal search | Real feedback failure; reduced reproducer; strict replay; actual saved input settings restored | `verification.spec.ts`, `test_verification.py` |
| Exports and replay | Six runtime record kinds; exact source identity; tampering, non-finite numbers and Boolean/type substitution rejected | Runtime record, `test_replay_integrity.py`, backend CLI checks |
| Request recovery | Revision conflicts; lost successful responses; reload and identical retry; read failure; cancellation/queue capacity | `live.spec.ts`, `test_reliability.py`, session-store checks |
| Process recovery | Abrupt termination; pending command preserved; retry without duplicate operation; transaction rollback | Restart record, `test_process_recovery.py`, `test_restoration_sessions.py` |
| Phone and keyboard | 390px layout; all controller tools; restoration/search; focus containment/return; reduced motion; topology selection | Browser journeys, runtime geometry/topology checks |
| Release and source | Locked dependency consistency; lint/format/build; CSV byte identity; SQLite exclusions; wheel resource and licenses | Full runner, `test_git_source.py`, `test_release_packaging.py`, `test_repository_integrity.py` |

Browser test files are in `frontend/tests/`; backend files are in `backend/tests/`.
The six runtime kinds are regression, temporal, failure search, live session,
controlled session and live dashboard. Their exports are checked with the
current implementation rather than only compared with cached UI text.

## Scope boundaries

- CI currently checks Linux full native/software verification and Windows
  operational compatibility separately; a different OpenDSS build can correctly
  reject Linux-frozen historical records on Windows.
- Platforms, browser engines and device combinations beyond the executed CI
  environments remain untested unless separate evidence is recorded.
- Chromium desktop and phone-viewport checks do not establish accessibility
  certification, physical feeder validation or safety for field operation.

The original native-default electrical comparison remains 52/56. The declared
constant-PQ v1 reference passes 56/56; the corrected public voltage reference
passes 29/29. These checks have different configurations and scopes. See the
[reference correction](REFERENCE_VALIDATION.md#published-targets-and-provenance).
