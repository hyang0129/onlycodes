# Weekly Cohort Retention Matrix

Growth is asking for a weekly cohort-retention matrix for users acquired over
the last 12 weeks: "of the users who signed up in week N, how many were still
active in week N, N+1, N+2, ..."

You are given two files under `workspace/`:

1. `signups.csv` — header row + data rows. Columns:
   - `user_id` (string, unique)
   - `signup_date` (ISO date `YYYY-MM-DD`, UTC)
2. `activity.csv` — header row + data rows. Columns:
   - `user_id` (string; may or may not appear in `signups.csv`)
   - `activity_date` (ISO date `YYYY-MM-DD`, UTC)

## Definitions

- A **week** is a Monday-starting ISO week bucket. For any date `d`, the
  week-start is `d - (d.weekday())` days (so Monday → same day, Sunday →
  6 days back). Use that Monday's ISO date string (`YYYY-MM-DD`) as the
  week's identifier.
- A user's **cohort week** = the week containing their `signup_date`.
- A user is "active in week W" iff there exists at least one row in
  `activity.csv` for that user with `activity_date` in week W.
- Users in `activity.csv` who are not in `signups.csv` MUST be ignored
  entirely.
- The cohort week counts the user even if they have no activity row; activity
  in week W (including the cohort week itself) contributes to the retention
  cell `(cohort, W)`.
- **Only include cohorts whose week-start date lies in the 12-week window
  ending on (and including) the latest `signup_date` in the file's Monday
  week.** That is: compute `max_monday` = Monday of the max `signup_date`
  across the signups file; the allowed cohort weeks are the 12 Mondays
  `max_monday - 11*7d, max_monday - 10*7d, ..., max_monday`. Skip any cohort
  whose week-start falls outside this set.

## Output

Write `output/retention.json`. Single JSON object with keys:

```json
{
  "cohorts": [
    {
      "cohort_week": "YYYY-MM-DD",   // the cohort's Monday
      "cohort_size": <int>,
      "retention": [
        {"week_offset": 0, "active_users": <int>, "retention_rate": <float>},
        {"week_offset": 1, "active_users": <int>, "retention_rate": <float>},
        ...
      ]
    },
    ...
  ]
}
```

- `cohorts` MUST be sorted by `cohort_week` ascending (oldest first).
- For each cohort, emit retention entries for `week_offset` from 0 through
  `(max_monday - cohort_week) / 7` **inclusive**. For the most recent cohort
  this is a single entry (offset 0); for the oldest cohort it is 12 entries
  (offsets 0..11).
- `week_offset` entries MUST be sorted ascending and contiguous starting at 0.
- `cohort_size` = number of users in the cohort.
- `active_users` = number of distinct users from the cohort who had activity
  in `cohort_week + week_offset * 7 days`.
- `retention_rate` = `active_users / cohort_size`, rounded to **4 decimal
  places**. If `cohort_size == 0`, emit `0.0` (but such cohorts must not be
  emitted — see next rule).
- **Skip cohorts with `cohort_size == 0`** — do not emit them at all. (If the
  12-week window contains a week with no signups, just omit it.)

Extra keys anywhere will fail the grader.

## Optional public verifier

`workspace/verify.py` exposes `verify(artifact_path: Path)` — shape only.

## Notes

- ~8,000 users, ~40,000 activity rows, 16-week span in the file. The grader
  picks the 12-week window off `max(signup_date)` consistently.
- `pandas`/`numpy`/`scipy`/`sklearn` + stdlib are available; no network.
- Strings compare as ISO dates lexicographically, so you can sort by
  `cohort_week` as strings.
