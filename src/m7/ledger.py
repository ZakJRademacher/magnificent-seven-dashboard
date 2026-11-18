"""Pipeline state: the published history, the run ledger and the status page data.

The state directory is kept on the repository's `data` branch, separate from code:

    prices.csv, risk_free.csv   the history currently published
    runs.jsonl                  one line per pipeline run, append-only
    events.jsonl                accepted dividends, splits and corrections, append-only
"""

import json
from pathlib import Path

import pandas as pd

from . import sessions

ON_TIME_HOUR_UTC = 24  # a session's prices are on time if live by midnight UTC that day (7-8pm New York)
SLO_TARGET = 0.95      # share of the last SLO_WINDOW sessions published on time
SLO_WINDOW = 30


class State:
    def __init__(self, root):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self.prices_csv, self.rates_csv = self.root / "prices.csv", self.root / "risk_free.csv"
        self.runs, self.events = self.root / "runs.jsonl", self.root / "events.jsonl"

    def has_history(self):
        return self.prices_csv.exists()

    def load(self):
        prices = pd.read_csv(self.prices_csv, index_col="Date", parse_dates=True)
        rates = None
        if self.rates_csv.exists():
            rates = pd.read_csv(self.rates_csv, index_col="Date", parse_dates=True)["risk_free"]
        return prices, rates

    def save(self, prices, rates):
        prices.to_csv(self.prices_csv, index_label="Date")
        if rates is not None:
            rates.to_csv(self.rates_csv, index_label="Date", float_format="%.5f")

    def append(self, path, record):
        with path.open("a", encoding="utf-8") as stream:
            stream.write(json.dumps(record, separators=(",", ":"), default=str) + "\n")

    def read(self, path):
        if not path.exists():
            return []
        return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def timeliness(runs, now=None, window=60):
    """For each recent session: when its prices first went live, and whether that was on time.

    Sessions before the ledger's first run are left out rather than guessed.
    """
    published = [r for r in runs if r["status"] in ("published", "degraded") and r.get("as_of")]
    if not runs:
        return []
    first_run = pd.Timestamp(runs[0]["finished"]).tz_convert("UTC")
    expected = sessions.expected_last_session(now)
    days = sessions.sessions_between(expected - pd.Timedelta(days=window * 2), expected)[-window:]
    out = []
    for day in days:
        deadline = (day + pd.Timedelta(hours=ON_TIME_HOUR_UTC)).tz_localize("UTC")
        if deadline < first_run:
            continue
        live = next((pd.Timestamp(r["finished"]).tz_convert("UTC") for r in published
                     if pd.Timestamp(r["as_of"]) >= day), None)
        if live is None:
            state = "missed" if pd.Timestamp(now or pd.Timestamp.now(tz="UTC")).tz_convert("UTC") > deadline else "pending"
        else:
            state = "on_time" if live <= deadline else "late"
        out.append({"session": f"{day:%Y-%m-%d}", "state": state,
                    "live_at": None if live is None else live.strftime("%Y-%m-%dT%H:%MZ")})
    return out


def status_payload(runs, events, now=None):
    """Everything the status page shows."""
    days = timeliness(runs, now)
    scored = [d for d in days if d["state"] != "pending"][-SLO_WINDOW:]
    on_time = sum(d["state"] == "on_time" for d in scored)
    latest = runs[-1] if runs else None
    return {
        "generated": pd.Timestamp(now or pd.Timestamp.now(tz="UTC")).tz_convert("UTC").strftime("%Y-%m-%dT%H:%MZ"),
        "slo": {"target": SLO_TARGET, "window": SLO_WINDOW, "on_time": on_time, "scored": len(scored),
                "rate": round(on_time / len(scored), 4) if scored else None},
        "latest": latest,
        "sessions": days,
        "runs": runs[-30:][::-1],
        "events": events[-20:][::-1],
    }


def badges(status, now=None):
    """Shields.io endpoint badges (https://shields.io/badges/endpoint-badge) for the README."""
    slo = status["slo"]
    if slo["rate"] is None:
        on_time = {"message": "no data yet", "color": "lightgrey"}
    else:
        color = "brightgreen" if slo["rate"] >= slo["target"] else "yellow" if slo["rate"] >= slo["target"] - 0.1 else "red"
        on_time = {"message": f"{slo['rate']:.0%} of last {slo['scored']} days", "color": color}
    latest = status["latest"]
    if latest and latest.get("as_of"):
        behind = sessions.sessions_behind(latest["as_of"], now)
        data = {"message": latest["as_of"], "color": "brightgreen" if behind == 0 else "yellow" if behind == 1 else "red"}
    else:
        data = {"message": "none", "color": "lightgrey"}
    return {"badge-on-time.json": {"schemaVersion": 1, "label": "on time", **on_time},
            "badge-data.json": {"schemaVersion": 1, "label": "data as of", **data}}
