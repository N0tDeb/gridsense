# Restoration after measurement refresh

Received demand bounds can change when donor measurements resume. Guarded control
includes bounds in its decision signature even when rounded demand means stay
the same. Such changes can trigger reconsideration after the cooldown; they do
not bypass pending confirmation, command caps or native checks.

The [protocol](../experiments/protocols/measurement_refresh.json) fixes three
inspected teaching-feeder cases before execution. Physical events, uncertainty
settings and electrical limits are retained. These are engineering conditions,
not a blind test set or a field-frequency estimate.

The first two cases drop donor load and LV-voltage measurements while device
availability and position continue to arrive. An outage interrupts 800 kW on
feeder A. Donor measurement delivery resumes later at the same true demand.
One case uses the default 10% initial uncertainty; the other begins at zero.
The near-limit case uses default uncertainty with B=1.45 and C=1.08.

## Recorded outcomes

Recorded on 12 October 2026. Affected-feeder restoration and whole-grid recovery
are separate: all three runs restore A, while a donor group remains disconnected.
No sequence cancellation occurs in these runs.

| Case | A fully supplied after outage | Whole grid fully supplied | Unserved kWh | Final unserved kW | All physical frames feasible | Strict replay |
| --- | ---: | --- | ---: | ---: | --- | --- |
| Default uncertainty, refresh at 15 s | 12 s | Not reached | 1.222 | 350.000 | Yes | Matched |
| Zero initial uncertainty, refresh at 10 s | 7 s | Not reached | 1.250 | 362.500 | Yes | Matched |
| Near-limit donor, refresh at 10 s | 7 s | Not reached | 1.250 | 362.500 | Yes | Matched |

The default case opens `tx_c2` at the decision made at 10 s, then closes `tie_c`
with the next decision at 11 s. Actual actuation supplies A at 12 s; 350 kW remains
unserved. The other cases open `tx_b2` at 5 s and close `tie_b` at 6 s; A is supplied
at 7 s, while 362.5 kW remains unserved. All six issued commands are confirmed.

The planner checks held-bound aging at assumed switching times and charges
transition energy. That does not resolve cold-load observability: a disconnected
group supplies zero power rather than a fresh estimate of its requested demand.
Resuming transport cannot infer that hidden demand from a deenergized reading.
Conservative sampled checks can therefore retain partial service. Restoring the
affected feeder early is not the same as restoring the whole grid or minimizing
actual total unserved energy.

The [execution planning guide](EXECUTION_PLANNING.md) defines the timing, energy
objective and conservative exposure restrictions. The [session comparison](SESSION_EVALUATION.md)
and [boundary challenge](SESSION_CHALLENGE.md) retain violations, service loss,
unresolved feedback and computation costs. Revalidation remains necessary when
new evidence changes a remaining sequence.

[Complete results](../experiments/refresh_results/results.json) and compressed
exports retain every native frame, received row, decision, command, confirmation
and logical action. The runner strictly replays each export under matching source
and native versions. Its report checker verifies identities, export checksums,
inputs, complete horizons and independent physical-frame accounting; it does not
rerun electrical replay.

```bash
python experiments/run_measurement_refresh.py --output-dir var/measurement-refresh
python experiments/run_measurement_refresh.py --output-dir var/measurement-refresh --verify-report
```

Use a new directory. `examples/measurement_refresh.json` is the default case in
ordinary episode format for `episode` and `replay-episode`. No repair or actuator
failure is present in these inputs. Whole-grid recovery must not be claimed for
these recorded runs.
