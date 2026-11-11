# Frozen boundary-case comparison

This directory is an immutable comparison dataset and its source/schema fixtures,
used by the boundary-case accounting checker. Its 75 episodes record a controller
that can open supplying backup before discovering that the remaining command
allowance cannot finish normal recovery. Those outcomes are separate from the
production controller's complete results in `../challenge_results/`.

The protocol, freeze, JSON/CSV outcomes, costs and compressed physical frames are
retained to verify the comparison faithfully. The `.py.txt` files are study
fixtures, not alternate application modules. All needed dependencies are included;
no preceding project archive or external development checkout is required.
[Study interpretation](../../docs/SESSION_CHALLENGE.md).

From the installed project root:

```bash
python scripts/check_challenge_discovery.py
```

This checks source identity, trace integrity, case counts, interval accounting
and table consistency under the recorded schema. It does not replay these
outcomes through the production controller or claim a blind holdout. Keep these
fixtures unchanged when maintaining the active source.
