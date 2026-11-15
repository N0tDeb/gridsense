# Switching times and restoration decisions

GridSense compares ordered switching sequences using received measurements.
A route must pass real OpenDSS checks before it can be selected. The planner also
accounts for the time spent waiting for switching and confirmation, and for demand
left disconnected during that sequence.

These are bounded decisions on a teaching feeder. The controller does not know
future demand changes, repair events, measurement arrivals or actuator failures.

## Public assumptions

`control.planning_timing` supplies three settings:

| Setting | Default | Meaning |
| --- | ---: | --- |
| `actuation_delay_s` | 1 s | Assumed time from issuing a command to changing position |
| `confirmation_delay_s` | 0 s | Additional assumed wait for position feedback |
| `energy_horizon_s` | 10 s | Common window for comparing predicted unserved energy |

The first two settings must fit the command confirmation timeout. A plan must
fit both the energy window and the remaining session horizon. Command allowance
also limits its length. The browser keeps these settings under **Planning
assumptions** when creating a session.

Scenario actuator settings are separate. A scenario may delay or fail a command,
or drop confirmation. The planner never reads those private settings. Its timing
assumption can therefore be wrong. Commands still wait for correlated actual
position feedback; a forecast cannot confirm a command.

## Future checks

For each operation, the planner checks its expected actuation time. It also
checks the last held tick before the next operation, or the final operation's
confirmation time. For example, two switches with a two-second actuation delay
and one-second confirmation delay are checked at offsets 2, 4, 5 and 6 seconds.

Held demand means stay unchanged. Guarded lower and upper bounds widen according
to the public uncertainty-growth setting, up to its declared cap. No future
measurement refresh is assumed. Existing evidence wider than the cap is retained.
Nominal checks the means; guarded checks up to 15 distinct demand points at each
tested time. Every electrical check rebuilds and solves the real native circuit.

The next command is checked again after actual confirmation, using newly received
evidence and the remaining horizon. This checks feasibility; it does not continually
rerank the entire remaining sequence by energy. A failed check cancels the remaining
sequence before replanning. Lost confirmation blocks further switching.

These sampled times and demand points do not establish continuous safety. The
final configuration is not stress-tested at every tick of the remaining energy
window. Unseen physical demand changes can still cause violations before the
controller receives evidence.

## Predicted unserved energy

Each candidate uses the same window: the smaller of the configured energy horizon
and remaining session time. Native nominal service is integrated for the initial
configuration, each intermediate configuration and the final hold. Intervals use
`[start, end)`; the terminal sample has zero duration.

The calculation assumes successful switching at the declared times and held
received demand means. It includes service interruption during break-before-make
recovery. Unknown electrical service produces unknown predicted energy, never a
zero loss. Inadmissible sequences receive no energy credit.

The live objective compares feasible sequences in this order:

1. Higher terminal critical supply.
2. Lower predicted critical unserved energy.
3. Lower predicted total unserved energy.
4. Higher terminal total supply.
5. Fewer switching operations.
6. Lower peak loading across the tested predictions.

kW ranks round to 0.1 kW, energy ranks to `1e-8` kWh, and operation keys settle
remaining ties. Terminal critical service takes priority over the energy terms;
this is an explicit operating preference, not a weighted social-cost model.
Returning to normal additionally requires that terminal critical and total
service do not decrease beyond the existing 0.1 kW comparison tolerance.

Predicted energy is shown with the decision. Actual episode energy comes from
physical OpenDSS frames and is recorded separately. The two need not agree.

## Received overloads and reconnection

A fresh loading reading above 100%, with device positions measured at the same
time, adds a correction restriction immediately. It does not wait for the
two-sample alarm latch. The first switch must reduce the connected load groups
using an overloaded device without increasing the exposure of another measured
overloaded device. Native feasibility checks still apply to every resulting step.

The controller remembers the device, its affected load set, the received demand
estimates and the raw overloaded row. It blocks reconnecting that set, or a
superset, through that device while those associated estimates remain unchanged
at 1 kW rounding. Changing an unrelated switch or another load's estimate cannot
clear the restriction. A changed estimate for an associated load allows a new
evaluation. Bounds changes alone do not erase the remembered exposure.

This is a conservative restriction. Graph membership does not model every
voltage interaction, so a physically useful alternative may be rejected. A
disconnected load supplies no new demand measurement, which can leave partial
service in place. The restriction is not proof that every forbidden combination
is physically impossible under changed conditions.

Newly observed equipment availability changes and overload changes bypass the
ordinary replanning cooldown. Pending confirmation, command and decision caps,
and native evaluation budgets still apply. Bounds and shrinking energy windows
can also trigger reconsideration, subject to the cooldown.

## Bounded search and measured cost

The search retains ordered paths, including different orders that reach the same
final topology. No device repeats within one plan. Modeled line toggles and
distribution-transformer disconnects can reroute or shed demand. Available
isolated main transformers and sources can be closed. Treating each distribution
disconnect as remotely commandable is a teaching-model assumption.

Connectivity supplies an optimistic service bound. A path is pruned only when
that bound cannot beat an already checked choice under the stated objective.
Connectivity never establishes electrical feasibility. Native problems are cached
only within one decision, by complete circuit state and connected-load demand.
Disabled-load model inputs stay fixed; requested demand still includes every load
group. Every guarded sample is evaluated, but identical electrical problems can
reuse a solve with separately calculated requested kW. Reconnection or a changed
connected demand requires a new solve. Cache hits do not consume the native budget.
The [native reuse comparison](NATIVE_REUSE.md) checks this behavior against a
full-demand-key reference on frozen inputs.

The default budget is 2,048 native calls per tick, shared between remaining-sequence
checks and replanning. Reports retain cache hits, structural sequences, pruned
paths, checked candidates and exhaustion. Exhaustion returns the best completed
checked choice, or an explicit refusal. It is not a global optimality result.

The small-case permutation reference constructs paths and computes ranking and
energy separately. It shares native physics, uncertainty samples and the device
load-set helper. Agreement tests the search implementation, not independent
physical validity. See [session evaluation](SESSION_EVALUATION.md) for the actual
comparisons and costs.
