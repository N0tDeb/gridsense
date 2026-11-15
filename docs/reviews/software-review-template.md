# Independent software review — uncompleted template

Status: **pending**. Reviewer/date/OS: not supplied. Attribution permission: not supplied.

1. Extract into a clean directory and follow SETUP.md without author assistance.
   Use [the review packet](../INDEPENDENT_REVIEW.md) and manually exercise the
   [feature journeys](../FLOW_VERIFICATION.md), including interruption/recovery.
2. Run `python scripts/verify.py`; attach verification.json and the full logs.
3. Record backend passed/failed/skipped/errors and browser results separately.
4. Reproduce a cached-action defect without a database. Explain the real constraint
   that rejects it and check that the good reference uses the same inputs.
5. Review whether experimental variants can receive true demand, change allowed
   actions or alter the oracle. Check action rejection versus electrical detection.
6. Add one selector through the documented interface in your own checkout; test it
   without editing the engine. Record time, ambiguity and unsuccessful attempts.
7. Review cancellation, queue capacity, CLI failure codes and late-preset handling.
8. Inspect the frozen study for omitted failures, incorrect denominators, changed
   protocols or misleading assertions of independent evidence.

Return: commands/log paths, confirmed defects, potential risks, usability issues,
reproduction successes/failures and any author help required. Separate opinions
from demonstrated failures. Do not publish your identity without permission.

Findings: _not yet supplied_. Recommendation: _not yet supplied_.
