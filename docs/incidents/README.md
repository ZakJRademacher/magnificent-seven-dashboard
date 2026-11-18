# Incident write-ups

One file per incident that lasted more than a day or needed a manual decision, named `YYYY-MM-DD-short-name.md`. Keep it short and blameless: what happened, why, and what changed so it can't recur.

## Template

```markdown
# YYYY-MM-DD: one-line summary

- **Incident issue:** #N
- **Duration:** first failed run → first healthy run (hours)
- **Impact:** which trading days were late or missed; whether any wrong data was published (it shouldn't be)

## What happened
Timeline in UTC, from the run ledger and the incident issue.

## Why
The cause, and why the checks caught it (or didn't).

## What changed
The fix, the test that now covers it, and any change to the checks or this runbook.
```

No incidents yet.
