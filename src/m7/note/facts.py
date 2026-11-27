"""The fact sheet behind the daily note.

Every figure the note can show is computed here, from the one price history the
pipeline has just published, and rendered to text here. The writer only chooses
which facts to mention; it never writes a number itself.

    build_facts(prices, as_of=None) -> dict

Definitions (adjusted closes, trading sessions only):
- 1-day return: close on as_of / close one session earlier - 1
- 5-day return: close on as_of / close five sessions earlier - 1
- year-to-date return: close on as_of / last close of the previous calendar year - 1
- group 1-day return: simple average of the seven stocks' 1-day returns (equal weight)
- gap to SPY: group 1-day return minus SPY's (stored as a ratio, shown in percentage points)
A return whose baseline isn't in the history is left out, never estimated. The
first session in the history has nothing to compare with, so it raises ValueError.

Percentages are shown to one decimal place, rounding halves away from zero. A
stock is "flat" when its 1-day return shows as 0.0%. Best, worst and biggest
mover compare the values as shown, so stocks that show the same figure tie.
"""

import hashlib
import json
from decimal import ROUND_HALF_UP, Decimal

import pandas as pd

from ..config import BENCHMARK, TICKERS

NAMES = {
    "AAPL": "Apple", "MSFT": "Microsoft", "GOOGL": "Alphabet", "AMZN": "Amazon",
    "NVDA": "Nvidia", "META": "Meta", "TSLA": "Tesla", BENCHMARK: "the S&P 500 fund (SPY)",
}


def shown(value, places=1):
    """A ratio as the percentage people see: 0.04236 -> Decimal('4.2'). Halves round away from zero.

    The ratio is first trimmed to 10 decimal places, because float division leaves
    exact halves slightly short (100.05 / 100 - 1 is 0.000499999...), and a half
    must still round up to 0.1%.
    """
    ratio = Decimal(repr(float(value))).quantize(Decimal("1e-10"))
    return (ratio * 100).quantize(Decimal(1).scaleb(-places), rounding=ROUND_HALF_UP)


def _pct(d):
    return f"{abs(d)}%"


def _move(d, up, down, flat):
    if d > 0:
        return f"{up} {_pct(d)}"
    if d < 0:
        return f"{down} {_pct(d)}"
    return flat


def _ret(prices, ticker, end, start):
    if start is None:
        return None
    return float(prices.at[end, ticker] / prices.at[start, ticker] - 1)


def build_facts(prices, as_of=None):
    """The fact sheet for one trading day. `prices` has one column per ticker plus SPY."""
    prices = prices.sort_index()
    index = prices.index
    as_of = index[-1] if as_of is None else pd.Timestamp(as_of)
    if as_of not in index:
        raise ValueError(f"{as_of:%Y-%m-%d} is not a trading day in the history")
    pos = index.get_loc(as_of)
    if pos < 1:
        raise ValueError(f"{as_of:%Y-%m-%d} has no earlier session to compare with")

    prev_1 = index[pos - 1]
    prev_5 = index[pos - 5] if pos >= 5 else None
    last_year = index[(index.year == as_of.year - 1) & (index <= as_of)]
    year_end = last_year[-1] if len(last_year) else None

    facts, raw = {}, {}

    def add(fact_id, value, text):
        facts[fact_id] = {"value": value, "text": text}
        raw[fact_id] = value

    add("date", as_of.strftime("%Y-%m-%d"), f"{as_of:%A, %B} {as_of.day}, {as_of.year}")
    shown_1d = {}
    for ticker in TICKERS + [BENCHMARK]:
        name = NAMES[ticker]
        close = float(prices.at[as_of, ticker])
        add(f"{ticker}.close", round(close, 2), f"${close:,.2f}")
        r1 = _ret(prices, ticker, as_of, prev_1)
        d1 = shown(r1)
        shown_1d[ticker] = d1
        change = _move(d1, "rose", "fell", "was flat")
        add(f"{ticker}.change_1d", r1, change)
        add(f"{ticker}.move_1d", r1, f"{name} {change}")
        for key, start, period in (("5d", prev_5, "over five trading days"),
                                   ("ytd", year_end, f"so far in {as_of.year}")):
            r = _ret(prices, ticker, as_of, start)
            if r is not None:
                text = _move(shown(r), "up", "down", "unchanged") + f" {period}"
                add(f"{ticker}.change_{key}", r, text)

    group = sum(_ret(prices, t, as_of, prev_1) for t in TICKERS) / len(TICKERS)
    add("group.move_1d", group,
        "the seven stocks " + _move(shown(group), "rose", "fell", "were flat") + " on average")
    gap = group - _ret(prices, BENCHMARK, as_of, prev_1)
    gap_pp = shown(gap)
    if gap_pp > 0:
        gap_text = f"{gap_pp} percentage points ahead of {NAMES[BENCHMARK]}"
    elif gap_pp < 0:
        gap_text = f"{abs(gap_pp)} percentage points behind {NAMES[BENCHMARK]}"
    else:
        gap_text = f"level with {NAMES[BENCHMARK]}"
    add("group.gap_to_spy_1d", gap, gap_text)

    seven = {t: shown_1d[t] for t in TICKERS}
    up = sorted(t for t, d in seven.items() if d > 0)
    down = sorted(t for t, d in seven.items() if d < 0)
    flat = sorted(t for t, d in seven.items() if d == 0)
    for key, group_list, verb in (("up", up, "rose"), ("down", down, "fell"), ("flat", flat, "were flat")):
        n = len(group_list)
        add(f"count.{key}", n, f"{n} of the seven {'was flat' if verb == 'were flat' and n == 1 else verb}")

    best, worst = max(seven.values()), min(seven.values())
    biggest = max(abs(d) for d in seven.values())
    claims = {
        "best_1d": sorted(t for t, d in seven.items() if d == best),
        "worst_1d": sorted(t for t, d in seven.items() if d == worst),
        "biggest_mover_1d": sorted(t for t, d in seven.items() if abs(d) == biggest),
        "up": up, "down": down, "flat": flat,
        "all_up": len(up) == 7, "all_down": len(down) == 7,
        "group_beat_spy": gap_pp > 0, "group_trailed_spy": gap_pp < 0,
    }

    digest = hashlib.sha256(json.dumps(raw, sort_keys=True, default=str).encode()).hexdigest()
    return {
        "as_of": as_of.strftime("%Y-%m-%d"),
        "previous_session": prev_1.strftime("%Y-%m-%d"),
        "five_sessions_back": prev_5.strftime("%Y-%m-%d") if prev_5 is not None else None,
        "previous_year_end": year_end.strftime("%Y-%m-%d") if year_end is not None else None,
        "facts": facts,
        "claims": claims,
        "hash": digest,
    }
