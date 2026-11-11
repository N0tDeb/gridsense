# Verification benchmark

192 portable cases; 576 controller outcomes; seeds 0–5.

| Feeder / fault | Group | Controller | Electrical passes | Full contract passes |
|---|---|---|---:|---:|
| teaching / feed_a | development | nominal-v1 | 39/48 | 26/48 |
| teaching / feed_a | development | guarded-v1 | 44/48 | 25/48 |
| teaching / feed_a | development | hold-v1 | 48/48 | 0/48 |
| teaching / seg_a | transfer | nominal-v1 | 48/48 | 0/48 |
| teaching / seg_a | transfer | guarded-v1 | 48/48 | 0/48 |
| teaching / seg_a | transfer | hold-v1 | 48/48 | 0/48 |
| ieee13 / 632670 | transfer | nominal-v1 | 19/48 | 13/48 |
| ieee13 / 632670 | transfer | guarded-v1 | 21/48 | 5/48 |
| ieee13 / 632670 | transfer | hold-v1 | 21/48 | 0/48 |
| ieee13 / 671692 | transfer | nominal-v1 | 20/48 | 13/48 |
| ieee13 / 671692 | transfer | guarded-v1 | 20/48 | 5/48 |
| ieee13 / 671692 | transfer | hold-v1 | 20/48 | 0/48 |

Paired random cases for all three controllers. Transfer groups excluded from controller development; electrical integration smoke checks were performed before this benchmark. This is not a blind external holdout. No model fitting or parameter tuning.

A pass requires service and electrical checks. Pre-existing violations and cases with no feasible restoration remain in the denominator and are classified separately in results.json.

Directed vs random: the fixed search study does not establish earlier discovery by directed search. See search_results/SUMMARY.md. The per-run signature counts here measure clustering; they are not a bug count.

| Temporal seed | First failure / 12 | Reduction evaluations | Reproduced |
|---|---:|---:|---|
| 0 | 4 | 11 | True |
| 1 | 3 | 15 | True |
| 2 | 3 | 17 | True |
| 3 | 1 | 13 | True |
| 4 | 1 | 10 | True |
| 5 | 1 | 19 | True |

Signature diversity counts observed constraint/element/action combinations, not distinct defects.
Temporal fixture tests one intentionally seeded state-machine defect; repeated seeds do not create new mechanisms.
Actual-demand reference is privileged and only labels attainability; it is not a competing equally informed controller.
Finite uncertainty samples, two small networks and two fault positions each cannot establish operational safety or field generalization.
The supplied paired search results are analyzed without treating their reanalysis as an independent discovery experiment.
