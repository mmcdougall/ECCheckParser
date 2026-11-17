# FY 2025-26 FAB motion-list validation

**Assessment:** Ready to use as the minutes-backed candidate list for the accomplishments email. It is not evidence of later Council action or implementation.

## What was checked

- The source set is the official canonical FAB agenda packets carrying minutes for held meetings from July 1, 2025 through June 30, 2026.
- The scanner resolves the held meeting date from the embedded minutes rather than the packet filename.
- Duplicate copies of the same minutes are removed.
- The candidate filter keeps explicit passes and affirmative recorded votes, then removes routine and procedural actions.
- A hand/model-reviewed fixture checks every retained record's date, packet file ID, physical page, outcome class, aye/no count, and a distinguishing phrase from the minutes.

## Reconciliation result

- Hand/model-reviewed list: **13 motions**
- Code-produced list: **13 motions**
- Missing from code: **0**
- Unexpected in code: **0**
- Order differences: **0**

Before procedural filtering, the code found four additional successful actions: the November 13 meeting-calendar adoption, the November 13 Comprehensive Financial Policy tabling motion, and two January 27 deferrals. Those are preserved by the general scanner and excluded only when `--exclude-procedural` is requested.

The calendar-alignment accomplishment described in the email is separate from this motion extraction. The code neither proves nor rejects that process claim.

## Reproduce the list

```bash
.venv/bin/python fab_motion_search.py \
  --from 2025-07-01 \
  --through 2026-06-30 \
  --successful-only \
  --exclude-routine \
  --exclude-procedural \
  --format markdown \
  --out data/artifacts/investigations/2026-08-28-fab-fy25-26-code-extracted-motions.md
```

The hand-reviewed expected set is `tests/fixtures/fab_fy25_26_accomplishment_motions.json`. The integration check scans nine named canonical packets and compares the extraction record-for-record with that fixture.

## Verification run

```text
python -m unittest discover -s tests
Ran 130 tests in 38.933s
OK
```

`git diff --check` and Python compilation of the motion scanner, CLI, and focused tests also passed.
