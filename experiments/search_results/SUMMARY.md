# Failure-search benchmark

1152 complete incident evaluations; 48 method runs; 24 trials per method; seeds 0–5.

| Controller | Scope | Method | Runs finding failure | Mean capped first trial ↓ | Failing trials | Mean run seconds |
|---|---|---|---:|---:|---:|---:|
| nominal | inside | directed | 2/6 | 21.17 | 12/144 | 7.16 |
| nominal | inside | random | 2/6 | 19.50 | 3/144 | 7.53 |
| nominal | unrestricted | directed | 6/6 | 5.83 | 83/144 | 7.50 |
| nominal | unrestricted | random | 6/6 | 3.67 | 34/144 | 7.26 |
| guarded | inside | directed | 0/6 | 25.00 | 0/144 | 7.74 |
| guarded | inside | random | 0/6 | 25.00 | 0/144 | 7.43 |
| guarded | unrestricted | directed | 6/6 | 8.83 | 67/144 | 7.59 |
| guarded | unrestricted | random | 6/6 | 8.50 | 14/144 | 7.33 |

A run without a failure is assigned budget+1 (25) only for the explicitly capped first-failure metric and paired comparison. It is not an observed discovery time.

Paired seeds, identical admissible 0.05 grid, same complete-incident budget, no repeated point within a method. First four points match. Alternate method order by seed. One unscored warm-up. No reduction costs included.

Six predetermined seeds per condition. One custom feeder and one fault location. Correlated failing scenarios are not distinct defects. Searcher sees simulator truth; controllers do not. No search result establishes field safety, calibrated risk, or research novelty.

Timing is environment dependent. Compare budgets and paired discovery outcomes first. Do not treat failing-trial counts as a utility failure probability. Inspect every seed, including no-hit runs, in results.json; trials.parquet contains all evaluated points and provenance metadata.
