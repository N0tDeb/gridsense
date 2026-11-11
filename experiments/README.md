# Reproducible studies

This directory contains declared protocols, complete validated result data and
runners that use the application's native electrical adapters. It is part of
GridSense's reproducibility surface, separate from the runtime database.

| Directory | Purpose |
| --- | --- |
| `protocols/` | Frozen settings, source identities and configuration definitions |
| `results/` | Snapshot case-grid outcomes |
| `search_results/` | Paired search traces and computation costs |
| `verification_results/` | Controller/service transfer comparisons |
| `quality_results/` | Fixed-seed comparisons, complete denominators and uncertainty calculations |
| `assurance_results/` | Expanded fault-injection inputs, outcomes and seeded-defect reproducers |
| `session_results/` | Clocked sessions, sequence reference and uncertainty checks |
| `challenge_results/` | Fixed boundary-case outcomes under the production controller |
| `challenge_discovery/` | Frozen comparison data/source fixtures for the boundary-case accounting checker |
| `refresh_results/` | Received-measurement and partial-service cases |
| `native_reuse_results/` | Exact native-problem reuse versus a full-demand reference |
| `configured_reference_results/`, `model_reference_results/`, `reference_sensitivity_results/` | Separately named electrical configurations |
| `examples/` | Portable source-matching regression, temporal and failure-search exports |

Read [evaluation](../docs/EVALUATION.md) for questions, metrics, findings and
commands. Use a new output directory; runners refuse replacement of evidence.
`--verify-report` checks the named stored report and, where documented, actually
reruns native comparisons. It is not a blanket claim to have rerun every campaign.
Wall-clock costs apply to the recorded host/run; native-call counts are more portable.

## Fixtures and retained identities

Only `backend/gridsense/` is the active simulation implementation. The `.py.txt`
files in `challenge_discovery/` are immutable study fixtures used in an isolated
namespace to validate their original schema/source identity and interval accounting.
They are not imported by application startup and must not replace active modules.
The checker deliberately distinguishes those outcomes from production-controller
outcomes on the same inspected inputs. This distinction prevents false claims of
blind validation or relabeling failed results.

Protocol revisions, predecessor hashes and native provenance are scientific
integrity records. They are retained where needed to interpret the included study;
no preceding application ZIP or development checkout is required. Generated
progress monitors, runtime databases and temporary captures are excluded.

All datasets here are synthetic engineering cases. They are not utility records,
a field population or independent measurements. Preserve unsuccessful searches,
unattainable contracts and unfavorable service/cost results when extending them.
