# Reproducible benchmark

Cartesian grid: 6 west loads × 4 east loads × 3 telemetry assumptions. All outcomes retained.

Nominal and guarded receive identical observations per case. Oracle alone receives actual demand.

No train/test claim; deterministic engineering scenarios on one custom feeder. Assumed uncertainty is not calibrated. Not evidence of utility performance or research novelty.

| Regime | Controller | Cases | Violations | Mean restored kW | Mean feasible restored kW |
| --- | --- | ---: | ---: | ---: | ---: |
| all | nominal | 72 | 11 | 916.7 | 763.9 |
| all | guarded | 72 | 3 | 866.7 | 825.0 |
| all | oracle | 72 | 0 | 850.0 | 850.0 |
| current | nominal | 24 | 0 | 850.0 | 850.0 |
| current | guarded | 24 | 0 | 850.0 | 850.0 |
| current | oracle | 24 | 0 | 850.0 | 850.0 |
| wide_assumed_range | nominal | 24 | 3 | 900.0 | 775.0 |
| wide_assumed_range | guarded | 24 | 0 | 850.0 | 850.0 |
| wide_assumed_range | oracle | 24 | 0 | 850.0 | 850.0 |
| narrow_assumed_range | nominal | 24 | 8 | 1000.0 | 666.7 |
| narrow_assumed_range | guarded | 24 | 3 | 900.0 | 775.0 |
| narrow_assumed_range | oracle | 24 | 0 | 850.0 | 850.0 |

Feasible restored kW gives zero credit to an outcome violating a modeled limit. It is reported alongside raw restored demand, not as a replacement for the violation count.

These are finite, correlated cases on one feeder. No statistical generalization or continuous uncertainty guarantee is inferred.

Implementation SHA-256: `89044955ffc19431f697a3c30bcb04c59b00efcb0457d50ef9130c6ffc4f4d72`

Reproduce: `python experiments/run_benchmark.py` from the project root in the installed environment.
