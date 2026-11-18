"""The daily pipeline: fetch, compare with what was published, check, publish, record.

    python -m m7.pipeline --state state --site site

Each run:
1. loads the published history from the state directory (bootstrapping from data/ the first time),
2. downloads the full adjusted history again (small, and it lets every run see restatements and
   heal any day an earlier run missed),
3. compares it with the published history: dividend and split rescalings are accepted and logged;
   anything else stops publishing,
4. checks the data contract (all NYSE sessions present, no implausible moves, freshness),
5. publishes site/data.json if nothing blocking failed, otherwise rebuilds it from the last good
   history so the page keeps showing correct data,
6. appends the run to the ledger and writes site/status.json for the status page.

Exit status: 0 when the run published (even with warnings), 1 when it failed.
"""

import argparse
import datetime as dt
import json
import os
import sys
import uuid
from pathlib import Path

import pandas as pd

from . import checks, data, ledger
from .config import ROOT, START


def fetch_live():
    prices = data.drop_unfinished_day(data.download_prices())
    return prices, data.download_risk_free()


def fixture_fetcher(folder):
    """Read a download from CSV files instead of the network (tests, offline rehearsal)."""
    def fetch():
        prices = pd.read_csv(Path(folder) / "prices.csv", index_col="Date", parse_dates=True)
        rates_csv = Path(folder) / "risk_free.csv"
        rates = pd.read_csv(rates_csv, index_col="Date", parse_dates=True)["risk_free"] if rates_csv.exists() else None
        return prices, rates
    return fetch


def _iso(ts):
    return pd.Timestamp(ts).tz_convert("UTC").strftime("%Y-%m-%dT%H:%M:%SZ")


def run(state_dir, site_dir, fetch=fetch_live, now=None, trigger="manual", accept_revisions=None):
    """Run once. Returns the ledger record (also appended to the state's runs.jsonl).

    accept_revisions: a person's reason for accepting history changes the checks can't explain.
    The changes and the reason are logged as an event; use only after inspecting the diff.
    """
    rehearsal = now is not None  # a pretend time: record it as the finish time too
    now = pd.Timestamp(now or dt.datetime.now(dt.timezone.utc))
    now = now.tz_localize("UTC") if now.tzinfo is None else now.tz_convert("UTC")
    state = ledger.State(state_dir)
    record = {"run_id": uuid.uuid4().hex[:12], "trigger": trigger, "started": _iso(now), "status": "failed",
              "as_of": None, "rows_added": 0, "events": [], "checks": [], "error": None}

    if not state.has_history():
        cached, cached_rates = data.load_cache()
        state.save(cached[data.SERIES], cached_rates)
        record["bootstrapped_from"] = "data/ (repository cache)"
    published, published_rates = state.load()
    published_rates = data.align_risk_free(published_rates, published.index)

    try:
        fetched, fetched_rates = fetch()
        raw = fetched.reindex(columns=data.SERIES).loc[START:]
        fetched = raw.dropna()
        incomplete = checks.dropped_days(raw)
        events, problems = checks.restatements(published, fetched)
        if problems and accept_revisions:
            events.append({"ticker": "*", "kind": "accepted_by_operator", "effective": None, "factor": None,
                           "reason": accept_revisions, "changes": problems})
            problems = []
        contract = checks.contract(fetched, fetched_rates, now) if len(fetched) else []
        aligned_rates = data.align_risk_free(fetched_rates, fetched.index) if len(fetched) else None
        if len(fetched) and fetched_rates is not None and aligned_rates is None:
            contract.append(checks.Check("risk_free_values", "warn", "T-bill yields looked wrong; using the fallback",
                                         blocks=False))
        if problems:
            contract.append(checks.Check("restatements", "fail", "; ".join(problems)))
        elif events:
            contract.append(checks.Check("restatements", "pass", f"{len(events)} accepted (dividends, splits, corrections)"))
        else:
            noise = checks.rounding_noise(published, fetched)
            contract.append(checks.Check("restatements", "pass", "published history unchanged"
                                         + (f" (largest rounding difference {noise:.4%})" if noise else "")))
        if incomplete:
            contract.append(checks.Check("download", "warn", "left out incomplete day(s): " + "; ".join(incomplete),
                                         blocks=False))
        if not len(fetched):
            contract.append(checks.Check("download", "fail", "the source returned no complete days"))
        record["checks"] = [c.to_dict() for c in contract]
        blocking = [c for c in contract if c.status == "fail" and c.blocks]
        if blocking:
            record["error"] = "; ".join(f"{c.name}: {c.detail}" for c in blocking)
        else:
            record["rows_added"] = int(len(fetched.index.difference(published.index)))
            record["events"] = events
            state.save(fetched, aligned_rates)
            for event in events:
                state.append(state.events, {**event, "run_id": record["run_id"], "logged": _iso(now)})
            published, published_rates = fetched, aligned_rates
            degraded = any(c.status == "fail" for c in contract)  # a non-blocking failure, i.e. stale data
            record["status"] = "degraded" if degraded else "published"
    except Exception as exc:  # network errors, source format changes: recorded, never published
        record["error"] = f"{type(exc).__name__}: {exc}"

    # The page always shows the last good history; the status page shows what happened.
    record["as_of"] = f"{published.index[-1]:%Y-%m-%d}"
    record["finished"] = _iso(now if rehearsal else pd.Timestamp.now(tz="UTC"))
    state.append(state.runs, record)
    site = Path(site_dir)
    site.mkdir(parents=True, exist_ok=True)
    payload = data.site_payload(published, published_rates, updated=now.to_pydatetime())
    (site / "data.json").write_text(json.dumps(payload, separators=(",", ":")))
    status = ledger.status_payload(state.read(state.runs), state.read(state.events), now)
    (site / "status.json").write_text(json.dumps(status, separators=(",", ":"), default=str))
    return record


def summary_markdown(record):
    icon = {"published": "✅", "degraded": "⚠️", "failed": "❌"}[record["status"]]
    lines = [f"### {icon} Pipeline run {record['run_id']}: {record['status']}", "",
             f"Data as of **{record['as_of']}**, {record['rows_added']} new day(s).", ""]
    if record["error"]:
        lines += [f"**Error:** {record['error']}", ""]
    lines += ["| Check | Status | Detail |", "|---|---|---|"]
    lines += [f"| {c['name']} | {c['status']} | {c['detail']} |" for c in record["checks"]]
    if record["events"]:
        lines += ["", "Accepted restatements: " + ", ".join(
            f"{e['ticker']} {e['kind']} {e['effective']} ×{e['factor']}" if e["kind"] != "accepted_by_operator"
            else f"operator accepted {len(e['changes'])} change(s): {e['reason']}" for e in record["events"])]
    return "\n".join(lines) + "\n"


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--state", type=Path, default=ROOT / "state")
    parser.add_argument("--site", type=Path, default=ROOT / "site")
    parser.add_argument("--fixture", type=Path, help="read the download from CSVs in this folder instead of Yahoo")
    parser.add_argument("--now", help="pretend the run happens at this UTC time (rehearsals)")
    parser.add_argument("--trigger", default=os.environ.get("GITHUB_EVENT_NAME", "manual"))
    parser.add_argument("--record", type=Path, help="also write this run's ledger record here")
    parser.add_argument("--accept-revisions", metavar="REASON",
                        help="accept history changes the checks can't explain, logging this reason (see docs/OPERATIONS.md)")
    args = parser.parse_args(argv)
    fetch = fixture_fetcher(args.fixture) if args.fixture else fetch_live
    record = run(args.state, args.site, fetch=fetch, now=args.now, trigger=args.trigger,
                 accept_revisions=args.accept_revisions or None)
    text = summary_markdown(record)
    print(text)
    if os.environ.get("GITHUB_STEP_SUMMARY"):
        with open(os.environ["GITHUB_STEP_SUMMARY"], "a", encoding="utf-8") as stream:
            stream.write(text)
    if args.record:
        args.record.write_text(json.dumps(record, indent=2, default=str))
    return 0 if record["status"] != "failed" else 1


if __name__ == "__main__":
    sys.exit(main())
