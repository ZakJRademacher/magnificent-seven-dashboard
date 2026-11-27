"""Pick the eval cases from the cached price history and freeze them.

    python evals/make_cases.py

Writes evals/cases/<date>.json for about 30 trading days chosen to cover the
situations a note has to handle: ordinary days, all seven up, all seven down,
flat stocks, very large moves, ties, days after a market holiday, the first
trading day of a year, and the group level with SPY.

Each case freezes the fact sheet the writer will see, plus the expected answers
for every checkable claim, worked out here with separate code (plain pandas, not
m7.note.facts), so the grader doesn't mark the fact sheet's own homework.
"""

import json
import math
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from m7.config import BENCHMARK, PRICES_CSV, TICKERS  # noqa: E402
from m7.note.facts import build_facts  # noqa: E402

CASES = ROOT / "evals" / "cases"
TARGET = 30


def tenths(ratio):
    """Percent to one decimal, halves away from zero, written independently of facts.shown."""
    x = round(abs(ratio) * 1000, 6)  # tenths of a percent, trimmed of float noise
    n = math.floor(x + 0.5)
    return int(math.copysign(n, ratio)) if n else 0


def expected_for(day, prices):
    """Expected claims for one day, from day-on-day returns of the seven and SPY."""
    i = prices.index.get_loc(day)
    r = prices.iloc[i] / prices.iloc[i - 1] - 1
    t = {k: tenths(r[k]) for k in TICKERS}
    best, worst = max(t.values()), min(t.values())
    biggest = max(abs(v) for v in t.values())
    up = sorted(k for k, v in t.items() if v > 0)
    down = sorted(k for k, v in t.items() if v < 0)
    group = sum(r[k] for k in TICKERS) / len(TICKERS)
    gap = tenths(group - r[BENCHMARK])
    return {
        "leader": sorted(k for k, v in t.items() if v == best),
        "laggard": sorted(k for k, v in t.items() if v == worst),
        "biggest_mover": sorted(k for k, v in t.items() if abs(v) == biggest),
        "up": up, "down": down, "flat": sorted(k for k, v in t.items() if v == 0),
        "all_up": len(up) == 7, "all_down": len(down) == 7,
        "most_up": len(up) >= 4, "most_down": len(down) >= 4,
        "group_beat_spy": gap > 0, "group_trailed_spy": gap < 0,
    }


def choose(prices):
    """(date, reason) pairs, most specific situations first, then evenly spaced ordinary days."""
    days = prices.index[1:]
    exp = {d: expected_for(d, prices) for d in days}
    ret = (prices[TICKERS] / prices[TICKERS].shift(1) - 1).loc[days]
    picks = {}

    def take(selected, reason, n):
        for d in selected:
            if n == 0:
                break
            if d not in picks:
                picks[d] = reason
                n -= 1

    take([d for d in days if d.year != prices.index[prices.index.get_loc(d) - 1].year], "first trading day of a year", 5)
    take([d for d in days if exp[d]["all_up"]][::40], "all seven up", 3)
    take([d for d in days if exp[d]["all_down"]][::40], "all seven down", 3)
    take(ret.abs().max(axis=1).sort_values(ascending=False).index, "very large single-stock move", 3)
    take([d for d in days if len(exp[d]["flat"]) >= 2], "two or more flat stocks", 2)
    take([d for d in days if (len(exp[d]["leader"]) > 1 or len(exp[d]["laggard"]) > 1) and len(exp[d]["flat"]) < 7],
         "tie for best or worst", 3)
    gaps = pd.Series(days, index=days).diff().dt.days
    take([d for d in days if gaps[d] >= 4 or (gaps[d] == 2 and d.weekday() != 0)], "first day after a market holiday", 3)
    take([d for d in days if not exp[d]["group_beat_spy"] and not exp[d]["group_trailed_spy"]],
         "group level with SPY", 2)
    remaining = TARGET - len(picks)
    if remaining > 0:
        step = max(1, len(days) // (remaining + 1))
        take([days[k] for k in range(step, len(days), step)], "ordinary day", remaining)
    return sorted(picks.items())


def main():
    prices = pd.read_csv(PRICES_CSV, index_col="Date", parse_dates=True)
    CASES.mkdir(parents=True, exist_ok=True)
    for old in CASES.glob("*.json"):
        old.unlink()
    chosen = choose(prices)
    for day, reason in chosen:
        case = {
            "id": f"{day:%Y-%m-%d}",
            "why": reason,
            "facts": build_facts(prices, day),
            "expected": expected_for(day, prices),
        }
        (CASES / f"{case['id']}.json").write_text(json.dumps(case, indent=1, default=str), encoding="utf-8")
    counts = pd.Series([r for _, r in chosen]).value_counts()
    print(f"Wrote {len(chosen)} cases to {CASES.relative_to(ROOT)}")
    print(counts.to_string())


if __name__ == "__main__":
    main()
