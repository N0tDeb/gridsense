# Fixed-protocol quality evaluation

1024 complete search trials; 64 method runs; 192 controller cases; 576 controller outcomes.

| Policy / scope | Method | Runs finding failure | Capped first trial | Adapter evaluations | Total seconds |
|---|---|---:|---:|---:|---:|
| nominal / inside | directed | 5/8 | 10.75 | 5504 | 38.53 |
| nominal / inside | random | 4/8 | 10.62 | 5504 | 39.52 |
| nominal / unrestricted | directed | 8/8 | 2.62 | 5504 | 38.72 |
| nominal / unrestricted | random | 8/8 | 2.25 | 5504 | 40.37 |
| guarded / inside | directed | 0/8 | 17.00 | 5504 | 40.39 |
| guarded / inside | random | 0/8 | 17.00 | 5504 | 40.78 |
| guarded / unrestricted | directed | 7/8 | 4.38 | 5504 | 40.78 |
| guarded / unrestricted | random | 8/8 | 4.00 | 5504 | 42.28 |

Paired discovery difference is **directed minus random**; negative favors directed. No hit is capped at 17.

| Policy / scope | Mean paired difference | Whole-seed bootstrap 95% interval |
|---|---:|---|
| nominal / inside | 0.12 | [-3.62, 4.12] |
| nominal / unrestricted | 0.38 | [0.00, 1.12] |
| guarded / inside | 0.00 | [0.00, 0.00] |
| guarded / unrestricted | 0.38 | [0.00, 0.88] |

| Feeder / fault | Controller | Electrical pass | Full contract pass | Eligible contract pass |
|---|---|---:|---:|---:|
| teaching / feed_a | nominal-v1 | 40/48 | 28/48 | 28/35 |
| teaching / feed_a | guarded-v1 | 47/48 | 26/48 | 26/35 |
| teaching / feed_a | hold-v1 | 48/48 | 0/48 | 0/35 |
| teaching / seg_a | nominal-v1 | 48/48 | 0/48 | N/A (0 eligible) |
| teaching / seg_a | guarded-v1 | 48/48 | 0/48 | N/A (0 eligible) |
| teaching / seg_a | hold-v1 | 48/48 | 0/48 | N/A (0 eligible) |
| ieee13 / 632670 | nominal-v1 | 27/48 | 11/48 | 11/27 |
| ieee13 / 632670 | guarded-v1 | 27/48 | 4/48 | 4/27 |
| ieee13 / 632670 | hold-v1 | 27/48 | 0/48 | 0/27 |
| ieee13 / 671692 | nominal-v1 | 27/48 | 11/48 | 11/27 |
| ieee13 / 671692 | guarded-v1 | 27/48 | 3/48 | 3/27 |
| ieee13 / 671692 | hold-v1 | 27/48 | 0/48 | 0/27 |

Eligible = initially feasible and contract attainable in the bounded action set using privileged truth. All cases remain in the preceding columns.

| Retained search | Status | Extra reduction trials | Extra adapter calls | Strict replay |
|---|---|---:|---:|---|
| nominal / inside, seed 100 | failure_found | 24 | 1032 | True |
| nominal / unrestricted, seed 100 | failure_found | 24 | 1032 | True |
| guarded / inside, seed 100 | no_failure_found | 0 | 0 | N/A: no failure |
| guarded / unrestricted, seed 100 | failure_found | 24 | 1032 | True |

Per-seed traces, paired hit-rate intervals, conditional controller intervals, case inputs, truth attainability and separate replay costs are retained in results.json. Both Parquet files include the same provenance manifest.

- New seeds on previously inspected small feeder models, not a blind external holdout.
- No controller, search, service threshold or uncertainty bound was tuned using these results.
- No-hit capped trial 17 is an administrative score, not an observed discovery time.
- Degenerate intervals do not establish equality or safety beyond this sample.
- Eligible means initially electrically feasible and service attainable within the bounded actions with privileged truth; all-case outcomes remain visible.
- Timings are sequential measurements on this machine, not portable speed guarantees.

Calls to ElectricalEngine.solve, including preconditions and intermediate states. Not native solver iterations. Only search/reduction/replay costs are metered.

Paired whole-seed percentile bootstrap, NumPy default_rng, 10000 draws. No independence claim for trials within a seed. No multiple-comparison correction.
