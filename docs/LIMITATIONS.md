# Scope and limitations

Live plans check assumed switching times, age held uncertainty bounds and compare
predicted transition energy. Timing and uncertainty settings are declared
assumptions, not measured response distributions or calibrated confidence bounds.
Checking finite demand/time points does not guarantee safety between them or after
an unseen physical change. Final holds are not stress-tested at every future tick.
Revalidation may still cancel a later operation, and conservative exposure memory
can retain partial service. See [execution planning](EXECUTION_PLANNING.md).

Native solve reuse reduces repeated electrical work for disconnected-load
combinations while retaining their requested demand. It does not recover hidden
demand, narrow uncertainty or guarantee that a bounded search completes. The
[frozen comparison](NATIVE_REUSE.md) retains exhausted searches and differing
budget-limited choices.

## Intended use

GridSense is a local restoration simulator and controller testbed. Live Grid starts
with available equipment and represents supplied outages, demand disturbances
and repair completion on a persistent integer-second clock. Browser, API and CLI
use bounded restoration, confirmed switching and checked reconnection. The separate
snapshot lab begins with a supplied isolated section and compares alternatives.
Neither workflow predicts equipment failure, discovers unknown faults, models
physical repair work, or operates field devices.

The live dashboard exposes simulator truth for explanation and scenario control;
received rows are labeled separately. This is not a real utility SCADA connection.
Playback is best-effort. Polling can lag a committed tick, and competing tabs or
playback can reject a stale action. An unknown HTTP outcome requires an identical
request retry; closing a tab does not pause the server. See
[Live dashboard](LIVE_DASHBOARD.md) for these operational limits.

The pinned POSIX native backend requires a UTF-8 locale for a non-ASCII working
directory. GridSense refuses that unsupported startup combination before native
import; it does not change the process locale or silently substitute another
solver. See [setup](../SETUP.md) for the startup options.

## Electrical models

The main lab uses a balanced teaching feeder. Controller tests also support a
modified unbalanced IEEE 13-node feeder. Added ties, ratings, priorities, fixed
taps, and voltage envelopes are experimental assumptions. OpenDSS solves are real;
realism depends on the model and inputs.

The reference checks 29 healthy-model voltages. Additional current/power targets
are derived from published quantities. Four of 56 combined checks fail under the
pinned defaults: three at load 675b and one power-balance residual.
[ASSURANCE.md](ASSURANCE.md) retains values and separate diagnostics. These checks
do not validate protection, switching transients, cold-load pickup, or utility
operating procedures.

The public voltage check uses corrected Official-column v2. Frozen v1
experiments retain the legacy dataset; their 692.3 target came from the
adjacent column. [Source correction](REFERENCE_VALIDATION.md#published-targets-and-provenance).

The [constant-PQ reference v1](REFERENCE_VALIDATION.md#constant-power-profile) passes the same 56
targets with an explicit 675b load-window override and tighter convergence.
It is a different reference configuration selected after diagnosis. Native
restoration inputs and the original 52/56 baseline retain their identities.

A separately named model-aware reference checks conditional power/current
envelopes using published voltages and the declared native load law, with tighter
numerical convergence. It preserves the four original mismatches. Its internal
balance and model-property checks must not be counted as independent physical
validation. Equipment outages are whole-device isolation assumptions; an MV tie
cannot supply a load through an unavailable transformer.

## Controllers and search

Snapshot ranking prioritizes critical service, total service, operation count and
loading. Live ranking additionally compares critical and total transition energy
after terminal critical service, using a common declared window. The full-information reference is best within
that candidate set. Snapshot guarded control samples three demand values; it can miss an
intervening violation, fail outside assumed bounds, or lose useful service.

Directed search is a heuristic compared with equal-budget random search. No-hit
runs remain inconclusive. Greedy reduction finds a simpler retained failure under
a budget; it does not establish a globally minimal cause.

## Data and evaluation

Inputs are synthetic; no ML model is trained. Fixed scenarios measure behavior
on those inputs. Seeded defects measure harness utility, not field failure rates
or general bug recall. The 28 reserved assurance cases were designed on known
models. The cases have been inspected; their partition labels do not establish
an unseen holdout. Failures, unattainable contracts, no-hit searches, and
unfavorable outcomes remain in the results. [EVALUATION.md](EVALUATION.md) defines
the comparisons and denominators. No research-novelty claim is made.

## Events, replay, and reviews

The event experiment has one commanded tie, explicit event ordering, actuation
failure, feedback delay, and timeout. It uses steady-state snapshots. Energy
totals depend on the recorded horizon. Strict replay requires original source and
native solver identity; current-code regression deliberately evaluates saved inputs
with current code. Review notes are local audit annotations, not ground truth,
model training, or multioperator adjudication.

Live teaching-feeder sessions use exact native samples with explicit delay/drop
settings, not a calibrated SCADA noise model. Two fresh limit violations raise
a numerical alarm by default; three fresh readings beyond its reset band clear
it. These are teaching rules, not validated fault classifiers. Equipment status
comes from modeled device state; no relay or protection dynamics are simulated.
Held-demand bounds grow by configured assumptions and are not calibrated confidence
intervals. Repairs are supplied events; optional control must separately check
and command reconnection. Session planning is limited to three operations without
repeating a device in one plan, and 2,048 native evaluations per tick by default.
The 15-point guarded set is not continuous robust optimization. The separate
permutation reference shares the physics and uncertainty model. Exhausting the
budget yields the best checked choice, possibly a hold, with no optimality claim.
The held power estimate assumes the model's fixed power factor; it is not a
general load-identification method.

Distribution-transformer disconnects are also treated as remotely commandable
load-shedding devices. This is a teaching assumption, not verified field hardware
or a protection operating procedure. Remembered overload exposure is deliberately
conservative and can reject a useful alternative influenced by wider voltage
coupling. Disconnected zero-power readings cannot reveal latent demand.

All modeled lines are assumed switchable at both ends. Available open transformers
and the source may close; voluntary transformer/source opening is outside the
planner's action set. No switch wear, transient interruption cost, crew dispatch,
cold-load pickup or field interlock protocol is modeled. Returning to normal is
an explicit operating preference; it can interrupt supply during break-before-make.
Missing command feedback can block recovery even if other sensors show supply.
Stale information can lead to real simulated overloads, including demand changes
outside the assumed uncertainty bounds. These are retained outcomes.
Sessions are limited to 600 simulated seconds, 128 pending events, two active
equipment incidents, and four simultaneously playing sessions. Playback speed
is a target; native work and database contention can make it slower.

## Deployment and validation

The service is for loopback, single-user use, with no authentication, multiuser
authorization or field-device integration. Snapshot experiment jobs do not
resume after interruption. Live sessions retain committed ticks and restart
paused; an in-flight transaction either commits completely or rolls back.
Only one local server process should own session pacing. Linux checks
are recorded in [VERIFICATION.md](VERIFICATION.md). Windows automation, hosted CI,
and external reviews remain pending in [review status](reviews/STATUS.json).
The pinned native wrapper retains newly created contexts. API workers are
recycled after each bounded request; the large search campaigns use fresh
sequential workers per seed-group. A custom long-running Python loop that keeps
creating contexts can still exhaust memory. No low-memory guarantee is made for
arbitrary workloads.
Original GridSense source and original documentation use [Apache 2.0](../LICENSE),
with Copyright 2026 [N0tDeb](https://github.com/N0tDeb). Bundled third-party
components retain their respective licenses; see [NOTICE](../NOTICE).
