# Magnificent Seven Dashboard

[![Pipeline](https://github.com/ZakJRademacher/magnificent-seven-dashboard/actions/workflows/update-dashboard.yml/badge.svg?branch=main)](https://github.com/ZakJRademacher/magnificent-seven-dashboard/actions/workflows/update-dashboard.yml) [![On time](https://img.shields.io/endpoint?url=https%3A%2F%2Fzakjrademacher.github.io%2Fmagnificent-seven-dashboard%2Fbadge-on-time.json)](https://zakjrademacher.github.io/magnificent-seven-dashboard/status.html) [![Data as of](https://img.shields.io/endpoint?url=https%3A%2F%2Fzakjrademacher.github.io%2Fmagnificent-seven-dashboard%2Fbadge-data.json)](https://zakjrademacher.github.io/magnificent-seven-dashboard/status.html)

![Magnificent Seven dashboard](magnificent_seven_dashboard.png)

**Live dashboard: <https://zakjrademacher.github.io/magnificent-seven-dashboard/>** · [Pipeline status](https://zakjrademacher.github.io/magnificent-seven-dashboard/status.html)

A risk and return dashboard for the seven largest US tech stocks (Apple, Microsoft, Alphabet, Amazon, Nvidia, Meta, Tesla), compared with the S&P 500. The live page refreshes itself every trading day.

## What it answers

- How much did each stock grow, and how does an equal-weight portfolio of all seven compare with the S&P 500?
- How risky was the ride (volatility, Sharpe ratio, drawdowns)?
- Do the seven actually diversify each other, or do they move together?
- Does a simple "momentum" signal beat the dumb baseline of always guessing "up"?

## Two outputs, one set of numbers

**Live dashboard (`site/`).** An interactive page with a 1Y / 2Y / 3Y / max period filter, hover readouts on every chart, and a full metrics table. It computes its metrics in the browser (`site/metrics.js`) from `site/data.json`, so the period filter works without a server.

**Static image (`magnificent_seven_dashboard.png`).** The one-page dashboard above, drawn with Matplotlib by `refresh.py` from the Python analysis in `src/m7/`.

The two are computed separately, so `tests/test_parity.py` runs the page's JavaScript in Node and checks that every metric, for every period button, matches the Python to within 1e-9.

## Run it locally

```
pip install -r requirements.txt
python refresh.py               # download fresh prices, update data/, site/data.json and the PNG
python refresh.py --offline     # rebuild from the cached data in data/ (no network)
python -m unittest discover -s tests -v
python -m http.server --directory site
```

Then open http://localhost:8000.

## How the live page updates

The page is rebuilt every weekday by an operated pipeline (`python -m m7.pipeline`), not just a scheduled script:

1. `.github/workflows/update-dashboard.yml` runs at 22:17 UTC on weekdays, on every push to `main`, and on demand.
2. The pipeline downloads the adjusted history from Yahoo Finance and **compares it with what it already published**, kept on the `data` branch. Dividend and split rescalings are accepted and logged; any other change to past prices stops publishing until a person looks.
3. It checks a **data contract**: every NYSE session present (including holidays and early closes), no implausible moves, and how far behind the latest settled close it is.
4. If anything blocking fails, the page keeps showing the last good history. Either way the run is appended to a ledger.
5. A failure **opens a GitHub issue** labelled `pipeline-incident`; the next healthy run closes it with how long it lasted.
6. The **[status page](https://zakjrademacher.github.io/magnificent-seven-dashboard/status.html)** shows whether each trading day went live on time (target: 95% by midnight UTC), every recent run, and every accepted restatement.

A separate **watchdog** workflow checks the ledger every morning and raises an incident if nothing has been published for two trading days, which catches a schedule that has silently stopped. The badges above show the latest run, the on-time rate and the latest trading day published.

Pull requests and other branches run the pipeline as a dry run against the live source. The [runbook](docs/OPERATIONS.md) covers the objectives, every check, and what to do for each kind of failure.

The page also shows a notice if its latest prices are more than five days old. GitHub turns off scheduled workflows in public repos after 60 days without activity; each scheduled run re-enables its own workflow to reset that clock.

`.github/workflows/tests.yml` rebuilds from the cached data and runs the tests on Python 3.10 and 3.12 for every push and pull request.

## Daily note

The card at the top of the page is a three-bullet summary of the latest trading day, written by an AI model (Claude Opus 5.5, through the Anthropic API) from the day's data. Every number in it is checked by code before it is published.

**How it is kept honest:**

1. **Code works out the facts.** `src/m7/note/facts.py` builds a fact sheet for the day: each stock's move, five-day and year-to-date change, the group average, the gap to the S&P 500, and which claims are true (who led, who lagged, how many rose).
2. **The model never types a number.** It answers in a fixed JSON shape and refers to figures by placeholder, like `{NVDA.move_1d}`. Code replaces each one with the fact's wording ("Nvidia rose 4.2%"), so every figure and every "rose" or "fell" comes from the data.
3. **A guard decides what is published** (`src/m7/note/guard.py`). It rejects a note if the model's own words contain a number or a direction word, if a claim like "led the group" isn't tagged or isn't true, if it names any other company, if it gives advice or predictions, or if it is too long.
4. **A failed note never holds back the prices.** It becomes a warning on the status page and the previous note stays up. A saved note is re-checked against the current data each time it is shown again.

**When it runs:** only on the scheduled run and manual runs of `main`, once per trading day. It costs about three cents a day. The API key is a secret of a protected `production` environment that only `main` can use, so branches and pull requests can't read it. Dry runs show a hand-written example note, labelled "Example".

**Evals:** `evals/` holds 30 past trading days chosen to cover the awkward cases (ties, all seven up or down, the first day of a year, flat stocks, holidays), each with answers worked out independently. Every prompt or model change is scored before and after. The release gate is code only: every note passes the guard and every tagged claim is correct. A second model scores clarity and tone, but its scores are only reported, because a model judge can vary between runs. The latest results are in `evals/results/`.

**Limits:** the note only describes what the prices did. It doesn't give reasons (no news), predictions or advice, and nothing is written on days the market is closed.

## Files

| Path | What it is |
|---|---|
| `refresh.py` | Downloads or loads prices, writes `site/data.json`, renders the PNG, prints the metrics |
| `src/m7/pipeline.py` | The operated daily run: fetch, compare with published history, check, publish, record |
| `src/m7/checks.py`, `src/m7/sessions.py` | Restatement detection, the data contract, and the NYSE trading calendar |
| `src/m7/note/` | The daily note: fact sheet, writer (API call), placeholder renderer, guard, pipeline step |
| `evals/` | The note's eval cases, grader and saved results |
| `src/m7/ledger.py`, `src/m7/incident.py` | Pipeline state, the run ledger and on-time measurement; GitHub incident issues |
| `site/status.html` | The public status page |
| `docs/OPERATIONS.md` | Objectives, checks and the runbook |
| `src/m7/data.py` | Downloads, sanity checks, the mid-day guard, and the cache in `data/` |
| `src/m7/metrics.py` | Returns, growth, drawdowns, CAGR, volatility, Sharpe ratio, correlation, honesty check |
| `src/m7/chart.py` | The static dashboard image |
| `src/m7/config.py` | Tickers, dates, colors and file paths |
| `site/index.html`, `site/metrics.js` | The live page and its in-browser metrics |
| `data/prices.csv`, `data/risk_free.csv` | Cached prices and T-bill yields from Nov 1, 2021 |
| `tests/` | Hand-worked metric checks, data guards, a fixed snapshot of published figures, and the Python/JavaScript parity check |

## Method notes

- Prices are adjusted for splits and dividends. Only days where all eight series have a price are used.
- The equal-weight portfolio holds one-seventh in each stock and rebalances daily, so its daily return is the average of the seven.
- CAGR compounds the total return over the period's length in trading years (252 trading days a year).
- Volatility is the sample standard deviation of daily returns, scaled to a year.
- Sharpe ratio is the average daily return above the risk-free rate, divided by the standard deviation of those excess returns, scaled to a year. The risk-free rate is each day's 13-week US Treasury bill yield, which went from near 0% in 2021 to over 5% in 2023. Because it uses the average daily return, a very volatile stock can have a positive Sharpe ratio while its compounded return is negative (TSLA over the full period).
- Drawdown is how far a series sits below its own running peak.
- The honesty check compares a momentum rule ("tomorrow goes the way today went") with always guessing "up". An edge smaller than about two standard errors of a 50/50 guess is treated as luck.

## Limits

- The seven were picked because they won, so looking back overstates what choosing in advance would have earned (survivorship bias).
- Results depend on the start date.
- This is analysis practice, not investment advice.

## Stack

Python, pandas, NumPy, Matplotlib, yfinance, exchange_calendars, the Anthropic API, plain HTML/SVG/JavaScript, GitHub Actions, GitHub Pages
