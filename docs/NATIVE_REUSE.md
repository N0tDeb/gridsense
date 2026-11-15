# Native solve reuse

Guarded planning checks demand combinations at the current and expected switching
states. A disconnected load still has requested demand, but its native load is
disabled and cannot consume power in that state. Varying only that disconnected
demand need not repeat the same electrical solve.

The predictor keeps disabled-load model inputs fixed to their received means. Its
cache key includes the complete circuit state and every connected load's demand.
Returned requested kW is calculated from all load groups for each query, including
disconnected groups. Cache hits therefore retain unserved demand rather than
treating an outage as zero consumption. Reconnection, a changed connected demand,
or another circuit state requires its own native solve. The cache lasts for one
decision; it does not reuse a prediction across later observations.

Every declared uncertainty sample is still evaluated. Native-call budgets count
actual adapter solves; a hit does not consume that budget. Voltage limits,
loading limits, allowed operations, switching times and the objective are unchanged.

## Frozen comparison

The [protocol](../experiments/protocols/native_reuse.json) contains eight synthetic
planning inputs created before changing reuse. Demand means vary independently
across the six load groups. Cases cover healthy operation, three feeder trips,
one transformer disconnect, alternate supply, an unavailable source and a tighter
feeder-trip case. Each runs at 192 and 2,048 native calls: 16 paired comparisons,
or 32 searches. The source and inputs are pinned in a separate
[freeze](../experiments/protocols/native_reuse.freeze.json).

The [full-demand reference](../experiments/native_reuse_reference.py) retains every
demand value in its cache key, including disconnected demand. It shares the native
adapter, finite uncertainty samples and search objective. This comparison tests
reuse and bounded-search behavior; it is not independent electrical validation.
Implementation order alternates by case. Wall times are single measurements on
one host, so native-call counts are the primary computation measure.

Recorded on 12 October 2026:

| Measure | Full-demand reference | Connected-demand reuse |
| --- | ---: | ---: |
| Planning native calls | 3,396 | 2,915 |
| Searches exhausting their budget | 3 | 2 |
| Searches returning no feasible choice | 0 | 0 |

Reuse saved 481 calls, or 14.2%, across these inputs. Thirteen pairs completed both
searches and selected identical actions and predictions within the declared
`1e-7` numerical comparison tolerance. All direct demand-sample probes matched,
including requested kW for disconnected loads.

The two 192-call feeder-trip pairs exhausted both budgets and chose different
completed candidates. Those differences remain in the report. In the 2,048-call
C-feeder trip, the full-demand reference exhausted its budget while reuse completed;
both selected the same candidate. A feasible source-open hold supplies no load:
feasibility alone does not establish restoration.

These are internal engineering inputs, not blind external cases or a deployment
population. More checked alternatives do not guarantee better actual service under
unseen demand. Reuse does not recover a disconnected load's current demand or
narrow its uncertainty. The [measurement-refresh cases](MEASUREMENT_REFRESH.md)
retain that observability limitation.

## Reproduce

After following SETUP.md, use a new directory:

```bash
python experiments/run_native_reuse.py --output-dir var/native-reuse
python experiments/run_native_reuse.py --output-dir var/native-reuse --verify-report
```

[Complete results](../experiments/native_reuse_results/results.json) retain both
selections, predictions, native-call counts, budgets, differences and probe outputs.
The checker verifies source/input identities, complete denominators, demand
accounting, instrumented native-call totals and completed-search comparisons. It
checks recorded evidence; the first command actually reruns the native comparison.
