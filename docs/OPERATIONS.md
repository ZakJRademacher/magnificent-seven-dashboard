# Operating the daily pipeline

The dashboard is rebuilt every weekday by `.github/workflows/update-dashboard.yml`, which runs `python -m m7.pipeline`. This page covers what the pipeline promises, how it checks itself, and what to do when it stops.

**Status page:** https://zakjrademacher.github.io/magnificent-seven-dashboard/status.html
**Incidents:** [issues labelled `pipeline-incident`](https://github.com/ZakJRademacher/magnificent-seven-dashboard/issues?q=label%3Apipeline-incident)

## What it promises

| Objective | Target | Measured by |
|---|---|---|
| Timeliness | Each NYSE trading day's closing prices are live by **midnight UTC** that day (7 or 8pm New York) | `ledger.timeliness`, from the run ledger |
| Reliability | **95%** of the last 30 trading days on time | `on time` figure on the status page |
| Correctness | Published history only changes through a dividend, a split, a small correction to the latest close, or a logged operator decision | restatement check and the `events` log |
| Safety | A failed run never replaces good data with bad; the page keeps showing the last good history | failed runs rebuild `data.json` from saved state |

The schedule runs at 22:17 UTC, 1 hour 17 minutes after the 4pm close in winter (EST) and 2 hours 17 minutes after it in summer (EDT), so a failed attempt can be re-run by hand and still be on time.

## How a run works

```
schedule ─▶ load published history (data branch) ─▶ download full adjusted history (Yahoo)
              │                                          │
              ▼                                          ▼
        compare overlap ◀───────────────────────── drop today if not settled
              │
   dividend / split / correction? ── yes ─▶ accept, log event
              │ no (anything else)
              ▼
         block publishing
              │
      data contract checks ──▶ publish data.json  or  rebuild it from last good history
              │
   append to runs.jsonl ─▶ commit state to data branch ─▶ open/close incident ─▶ deploy site + status page
```

Every run downloads the whole history again. It is small (five years × eight series) and it means a missed day heals itself on the next successful run, with no separate backfill step. It also lets every run see restatements.

### State

The `data` branch holds the pipeline's memory, separate from code history:

| File | Contents |
|---|---|
| `prices.csv`, `risk_free.csv` | The history currently published |
| `runs.jsonl` | One line per run: status, data as of, new days, every check, error |
| `events.jsonl` | Every accepted dividend, split, correction and operator decision |

The first production run bootstraps the state from `data/` in the main branch.

### Checks

| Check | Fails when | Blocks publishing |
|---|---|---|
| `schema` | The eight series aren't all present | yes |
| `complete` | A price is missing, zero or negative | yes |
| `ordered` | Dates repeat or go backwards | yes |
| `calendar` | An NYSE session is missing, or a non-trading date appears (exchange_calendars XNYS, including early closes) | yes |
| `moves` | A one-day move above 50% (warns above 25%; META's real −26% on 2022-02-03 is a warning) | yes |
| `restatements` | Published history changed in a way no dividend or split explains | yes |
| `download` | The source returned no complete days | yes |
| `download` (warning) | A recent day came back with a price missing, so it was left out; names the day and ticker. The next run usually fills it | no |
| `freshness` | More than one settled session behind (warns at one) | no: old prices are still correct, so they stay live and an incident opens |
| `risk_free` | The T-bill series is missing or implausible (warns; Sharpe falls back to a fixed 4%) | no |

### Restatements

Adjusted closes change in the past: on an ex-dividend date the source multiplies every earlier price by one factor slightly below 1, and on a split by a large factor. The pipeline compares the new download with the published history, ticker by ticker, and accepts the change only if it is a step function of that shape:

- earlier prices scaled **down** by one factor up to a date (dividend; split if the factor is far from 1),
- earlier prices scaled **up** by at least 1.5× (reverse split),
- every published day rescaled because the ex-date is the new day in the download,
- only the newest published close revised, by at most 1% (late correction).

Differences up to 0.002% are treated as rounding: Yahoo recomputes adjusted closes on every download, and the first production run saw SPY's Nov 16, 2026 close come back as 739.95 instead of 739.96. The largest such difference is shown in the check's detail.

Anything else, such as one past day edited, prices rising slightly in the past, or published days disappearing, blocks the run.

## When something goes wrong

A failed or stale run opens an issue labelled `pipeline-incident` (or comments on the open one) with the reason, a link to the run log, and the status page. The next healthy run comments with how long the incident lasted and closes it. The workflow run is also marked red.

| Symptom in the incident | Likely cause | What to do |
|---|---|---|
| `ConnectionError`, `HTTP 429`, "returned no data" | Yahoo is down or rate-limiting | Nothing usually: the next scheduled run self-heals. If it's before midnight UTC, re-run from the Actions tab to stay on time. |
| `restatements: … without a dividend or split pattern` | Yahoo revised past prices | Compare the changed days with a second source (Nasdaq, the company's investor site). If Yahoo corrected a bad print, re-run with **Run workflow → accept_revisions** set to a short reason; it is logged in `events.jsonl` and on the status page. If Yahoo is wrong, wait and let the next run re-check. |
| `restatements: … missing from the new download` | Yahoo returned a shorter history | Treat as a source fault; re-run later. Don't accept. |
| `calendar: missing N session(s)` | One ticker lacks a day, so that day was dropped | Usually transient; re-run. If it persists, check that ticker on Yahoo. |
| `moves: largest one-day move …` above 50% | Bad print or unadjusted split | Check the ticker's news. A real split will show up as a restatement once Yahoo adjusts. |
| `freshness` failing with no error | Yahoo hasn't published the close yet, or the schedule didn't fire | Check the Actions tab for the scheduled run. Re-run by hand. |
| "The pipeline crashed before it could record the run" | A code or dependency failure (for example a yfinance format change) | Read the log, reproduce with `python -m m7.pipeline --state /tmp/state --site /tmp/site`, fix, push. |
| No runs at all for days | GitHub disabled the scheduled workflow | Re-enable it on the Actions tab. The `keepalive` job and daily commits to `data` should prevent this. |

### Rehearsing a failure

Every scenario above can be replayed without the network:

```
PYTHONPATH=src python -m m7.pipeline --state /tmp/state --site /tmp/site \
    --fixture path/to/download --now 2026-11-16T22:17Z
```

`--fixture` reads `prices.csv` (and optionally `risk_free.csv`) instead of calling Yahoo, and `--now` pretends the run happens at that time. `tests/test_pipeline.py` covers outages, revisions, dividends, splits, staleness, operator overrides, timeliness and incident decisions this way.

## Incident write-ups

For any incident that lasted more than a day or needed a manual decision, add a short write-up to [`docs/incidents/`](incidents/) using the template there.
