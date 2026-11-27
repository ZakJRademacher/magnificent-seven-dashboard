# Plan: a daily market note on the dashboard

Status: draft v2, revised after an independent review. Branch: `feature/daily-market-note`. Nothing here is live until the branch is merged.

## Goal

After each trading day's refresh, the dashboard shows a short written note (a headline and three bullets) describing what the seven stocks did. An AI model chooses **what to say and how to phrase it**; code supplies **every number and every direction word**. If a note fails a check, the previous note stays up and the run records why.

Shown under the note, as agreed:

> Written by an AI model from the data above; every number is checked by code before publishing.

The note **describes** what happened. It never predicts, recommends, or gives advice.

## Key design choice: the model never writes numbers

The model writes sentences with **placeholders** that point at fact-sheet entries, for example:

> `{NVDA.move_1d}` and led the group, while `{TSLA.move_1d}`.

Code renders each placeholder from the fact sheet into text such as "Nvidia rose 4.2%" or "Tesla fell 1.8%". So a number can't be mistyped, rounded wrongly, attached to the wrong stock, or given the wrong direction. Any digit the model writes directly is rejected. Claims without numbers ("led the group", "all seven") are made through tagged claims the guard checks against the facts (below).

## What gets built

### 1. Fact sheet (`src/m7/note/facts.py`)
`build_facts(prices, as_of)` is a pure function over **the single history the pipeline has just published** (one snapshot, so dividend or split restatements can't mix old and new adjusted closes).
- 1-day return: close on `as_of` ÷ close one trading session earlier − 1.
- 5-day return: ÷ close five sessions earlier − 1.
- Year-to-date return: ÷ **the last close of the previous calendar year** − 1 (so the first trading day of January already counts its own move).
- A return whose baseline is missing is left out, never guessed.
- Group 1-day return: the simple average of the seven stocks' 1-day returns (equal weight). The gap to SPY is reported in **percentage points**.
- Biggest gainer and loser by 1-day return; "biggest mover" by absolute 1-day return. Ties are reported as ties. A stock counts as "flat" when its 1-day return rounds to 0.0%.
- Each entry has an id (`NVDA.move_1d`, `group.move_1d`, `spy_gap_1d`, …), the raw value, and the rendered phrase.

Unit tests use hand-checked values from `data/prices.csv`, including a January date, a tie and a flat day. The formulas get an independent check.

### 2. Writer (`src/m7/note/write.py`)
- Official Anthropic Python SDK (`anthropic`), model `claude-opus-5-5`, one non-streaming request per day, with a request timeout.
- Input: **numbers and fixed labels only**, no free text from outside (no news, no web pages), so there's nothing to inject instructions through.
- Structured output (`output_config.format`, JSON schema): `{headline, bullets: [{text, claims: [...]}]}`, where text uses placeholders and `claims` lists tagged claims such as `{"type": "leader", "id": "NVDA"}` or `{"type": "all_up"}`.
- System prompt: describe only; use placeholders for every figure; no predictions, opinions, advice, or causes that aren't in the data; plain English for a non-expert.
- Effort starts at the default (`medium`); the evals decide whether `low` holds quality.
- A refusal or any ending other than a normal finish counts as a failed note (no fallback model in v1).
- Logs model, token counts and the request id. Never logs headers or the key.

### 3. Guard (`src/m7/note/guard.py`)
Runs before anything can be published. A note fails if:
- it doesn't match the schema, or has other than exactly three bullets;
- any placeholder points at an unknown fact id;
- the model's text contains **any digit, spelled-out number** ("two", "half", "dozen"), "percent", "%", "$", or a date;
- a tagged claim is false against the facts (`leader` must be the biggest gainer, `laggard` the biggest loser, `all_up` / `all_down` / `most_up` must hold, ties named as ties);
- untagged superlatives or totals appear ("biggest", "best", "worst", "all", "every", "only", "record") outside a tagged claim;
- advice or prediction language appears (buy, sell, hold, should, recommend, expect, will, likely, target, forecast, outlook, opportunity, and similar);
- a company or ticker outside the eight known ones appears;
- length limits are broken (headline ≤ 90 characters, bullets ≤ 200 each, after rendering).

Adversarial unit tests feed it deliberately bad notes (a typed number, "two percent", a wrong leader, an untagged "all seven", an advice word, an unknown company) and must catch every one. No API key needed.

### 4. Pipeline and workflow
- **When**: only on the scheduled run and on manual runs of `main`. Pushes to `main` (including the merge itself), branch pushes and pull requests never generate a note.
- **Where in the run**: after the price checks pass and the history is saved, before the ledger and site files are written, so the run record includes the note result. A note failure is a non-blocking `note` check (`warn`) and never affects the price data.
- **State**: the last good note is saved with the pipeline state on the `data` branch (`state/note.json`) with its date and a hash of the facts it was written from. A rerun for a date that already has a note for the same facts does nothing; if the facts for that date changed (a restatement), the note is regenerated.
- **Secret**: `ANTHROPIC_API_KEY` is stored as a secret of a protected **`production` environment** that only `main` can use, and given only to the note step. It isn't a plain repository secret, so a branch push or pull request can't read it, even with an edited workflow.
- **Existing permissions (found in review)**: the build job currently has `contents: write`, `issues: write` and persisted credentials on dry runs too. Fix in this branch: dry runs get read-only permissions and no persisted credentials; production keeps what it needs.
- The `pages` concurrency group stays as it is, so production runs never overlap.

### 5. Page (`site/index.html`)
- A new card above "Growth of $100": headline, three bullets, the note's date, the disclosure line, and a link to the method section in the README.
- Inserted with `textContent` only (never `innerHTML`).
- No note, or a note older than the data: the card says so plainly.
- Dry runs show a saved example note marked "example".

### 6. Evals (`evals/`)
- `evals/cases/`: about 30 fact sheets from past trading days in `data/prices.csv`: ordinary days, all seven up, all seven down, a flat day, a very large mover, a day after a holiday, a tie for biggest mover, and the first trading day of a year. Each case stores the **expected answers** for its checkable claims (who led, who lagged, how many rose).
- `evals/run_evals.py`: generates notes (live API, costs money, run on purpose) or re-grades saved notes (free).
- **Release gate (code only)**: 100% of notes pass the guard, and every tagged claim matches the case's expected answer.
- **Judge (reported, not a gate)**: `claude-sonnet-5-5` scores each note 1–5 for clarity to a non-expert and neutral tone, against a written rubric, with a one-line reason. Its scores are tracked across prompt changes and spot-checked by a person. It doesn't block a release, because a model judge can vary between runs and favour certain styles.
- Results saved as `evals/results/<date>-<label>.json` with model, effort, prompt version, scores and cost; every prompt, model or settings change is scored before and after.

### 7. Docs and release
- README: a "Daily note" section (what it is, the disclosure, how it's checked, its limits).
- `docs/OPERATIONS.md`: note failure modes, how to rerun, how to switch the note off.
- CHANGELOG and VERSION `1.1.0`. The merge and the release each need Zak's yes.
- `anthropic` added to `requirements.txt` and the workflow's install step.

## Cost (estimates; measured before scheduling)
- Daily note: about 1,500 input and 400 output tokens on Claude Opus 5.5 ($4/$20 per million tokens): about **$0.01–0.02 per day**, roughly $5 a year.
- One full eval run (30 notes plus 30 judge calls): about **$0.50–1.00**.
- Zak sets a monthly spend limit on the API account as a backstop.

## Out of scope for v1
News or reasons behind moves; weekend or holiday notes; email or social posting; wording that compares the stocks as investments; refusal fallback models.

## Build order
1. Fact sheet + tests (formulas independently checked).
2. Placeholder renderer + guard + adversarial tests.
3. Writer with a saved example response; dry-run card on the page.
4. Workflow permission fix and the `production` environment (Zak creates the environment and its secret).
5. Evals; first live eval run (needs the API key; cost shown first).
6. Pipeline integration; docs.
7. Pull request, independent review, Zak's yes to merge; watch the first scheduled run.

Zak writes (with help): the eval's claim grader, so every part can be explained in an interview. (The guard's banned-number check was offered too; Zak chose to have it written for him.)

## Acceptance
- All existing tests still pass; new unit tests for facts, renderer, guard and writer (mocked) pass without an API key.
- Eval release gate met and recorded in `evals/results/`.
- A dry run on the branch shows the example card; a deliberately broken note is rejected and the previous note stays.
- Dry runs have read-only permissions; the API key is only reachable from `main` production runs.
- No AI attribution anywhere except the agreed disclosure line on the page and README.

## Open questions
1. Effort `medium` or `low`: decided by the evals.
