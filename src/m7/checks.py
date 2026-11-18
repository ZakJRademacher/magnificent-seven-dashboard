"""The pipeline's data contract and restatement detection.

Every run compares what the source returned with what was already published.
Adjusted closes legitimately change in the past: a dividend or split rescales
every earlier price by one factor. That pattern is accepted and logged. Any
other change to published history stops publishing until a person looks.
"""

from dataclasses import asdict, dataclass

import numpy as np
import pandas as pd

from . import sessions
from .data import SERIES

# Yahoo recomputes adjusted closes on every download, so the same day can come back slightly
# different: up to 1.35e-5 relative was seen in production (SPY 739.96 vs 739.95, Nov 16, 2026).
# Differences up to NOISE are rounding, not revisions. The smallest real dividend adjustment for
# these stocks (about 6e-5, NVDA's $0.01 on a $180 price) stays well above it.
NOISE = 2e-5
CORRECTION_LIMIT = 0.01  # a revision of the latest published close up to 1% is a late correction
WARN_MOVE, FAIL_MOVE = 0.25, 0.50  # one-day moves for these stocks beyond this are suspicious
REVERSE_SPLIT_MIN = 1.5  # smallest upward rescaling of earlier prices that a reverse split explains


@dataclass
class Check:
    name: str
    status: str      # "pass", "warn" or "fail"
    detail: str
    blocks: bool = True  # whether a failure stops publishing (staleness doesn't: old data is still correct)

    def to_dict(self):
        return asdict(self)


def _segments(ratio):
    """Split a series into runs of (nearly) equal values: [(start, end, value), ...]."""
    out, start = [], 0
    values = ratio.to_numpy()
    for i in range(1, len(values) + 1):
        if i == len(values) or abs(values[i] / values[start] - 1) > NOISE:
            out.append((start, i - 1, float(np.median(values[start:i]))))
            start = i
    return out


def rounding_noise(published, fetched):
    """The largest relative difference on overlapping days (rounding when below NOISE)."""
    common = published.index.intersection(fetched.index)
    if not len(common):
        return 0.0
    return float((fetched.loc[common, SERIES] / published.loc[common, SERIES] - 1).abs().max().max())


def dropped_days(raw, recent=5):
    """Recent days the source returned with a price missing, which the pipeline has to leave out."""
    tail = raw.iloc[-recent:]
    return [f"{day:%Y-%m-%d} (no price for {', '.join(row.index[row.isna()])})"
            for day, row in tail.iterrows() if row.isna().any()]


def restatements(published, fetched):
    """Compare overlapping history. Returns (events, problems).

    events: accepted changes, each {"ticker", "kind", "effective", "factor"}.
    problems: descriptions of changes that don't fit a corporate-action pattern.
    """
    events, problems = [], []
    lost = published.index.difference(fetched.index)
    if len(lost):
        problems.append(f"{len(lost)} published days are missing from the new download (first {lost[0]:%Y-%m-%d})")
    common = published.index.intersection(fetched.index)
    for ticker in SERIES:
        ratio = fetched.loc[common, ticker] / published.loc[common, ticker]
        if (ratio.sub(1).abs() <= NOISE).all():
            continue
        segments = _segments(ratio)
        last_start, last_end, last_value = segments[-1]
        if abs(last_value - 1) > NOISE and last_start == last_end and len(segments) >= 2 \
                and abs(segments[-2][2] - 1) <= NOISE and abs(last_value - 1) <= CORRECTION_LIMIT:
            # Only the newest published day differs, by a little: a late correction to that close.
            events.append({"ticker": ticker, "kind": "correction", "effective": f"{common[-1]:%Y-%m-%d}",
                           "factor": round(last_value, 8)})
            continue
        steps = [(end + 1, value / after) for (_, end, value), (_, _, after) in zip(segments[:-1], segments[1:])]
        dates = list(common)
        if abs(last_value - 1) > NOISE:
            # Every published day was rescaled: the ex-date is the first new day in the download.
            newer = fetched.index[fetched.index > common[-1]]
            if not len(newer) or last_end - last_start < 1:
                problems.append(f"{ticker}: recent prices changed by up to {ratio.sub(1).abs().max():.2%} without a "
                                "dividend or split pattern")
                continue
            steps.append((len(dates), last_value))
            dates.append(newer[0])
        if len(steps) > 3:
            problems.append(f"{ticker}: history changed irregularly ({len(segments)} distinct revisions)")
            continue
        # Dividends and splits scale earlier prices down; reverse splits scale them up by a large
        # factor. A small upward step has no corporate-action explanation (e.g. one edited day).
        odd = [f for _, f in steps if REVERSE_SPLIT_MIN > f >= 1]
        if odd:
            problems.append(f"{ticker}: earlier prices rose by {odd[0] - 1:.2%}, which no dividend or split explains")
            continue
        # Each step back in time multiplies earlier prices by one more factor (a dividend or split).
        for index, factor in steps:
            events.append({"ticker": ticker, "kind": "split" if abs(np.log(factor)) > 0.1 else "dividend",
                           "effective": f"{dates[index]:%Y-%m-%d}", "factor": round(factor, 8)})
    return events, problems


def contract(prices, rates, now=None):
    """Checks on the history about to be published."""
    checks = []
    columns_ok = list(prices.columns) == SERIES
    checks.append(Check("schema", "pass" if columns_ok else "fail",
                        "all eight series present" if columns_ok else f"columns are {list(prices.columns)}"))
    complete = prices.notna().all().all() and (prices > 0).all().all()
    checks.append(Check("complete", "pass" if complete else "fail",
                        "every price present and positive" if complete else "missing or non-positive prices"))
    ordered = prices.index.is_monotonic_increasing and not prices.index.has_duplicates
    checks.append(Check("ordered", "pass" if ordered else "fail",
                        "dates increase with no repeats" if ordered else "dates out of order or repeated"))

    expected = sessions.sessions_between(prices.index[0], prices.index[-1])
    missing, extra = expected.difference(prices.index), prices.index.difference(expected)
    gaps = [f"missing {len(missing)} session(s), first {missing[0]:%Y-%m-%d}"] if len(missing) else []
    gaps += [f"{len(extra)} non-trading date(s), first {extra[0]:%Y-%m-%d}"] if len(extra) else []
    checks.append(Check("calendar", "fail" if gaps else "pass",
                        "; ".join(gaps) or f"all {len(expected):,} NYSE sessions present"))

    moves = prices.pct_change().abs().iloc[1:]
    worst = moves.stack().idxmax() if len(moves) else None
    biggest = moves.stack().max() if len(moves) else 0.0
    status = "fail" if biggest > FAIL_MOVE else "warn" if biggest > WARN_MOVE else "pass"
    checks.append(Check("moves", status, f"largest one-day move {biggest:.1%}"
                        + (f" ({worst[1]} on {worst[0]:%Y-%m-%d})" if worst is not None else "")))

    behind = sessions.sessions_behind(prices.index[-1], now)
    expected_last = sessions.expected_last_session(now)
    status = "pass" if behind == 0 else "warn" if behind == 1 else "fail"
    checks.append(Check("freshness", status,
                        f"latest {prices.index[-1]:%Y-%m-%d}, expected {expected_last:%Y-%m-%d}"
                        + (f" ({behind} session(s) behind)" if behind else ""), blocks=False))

    checks.append(Check("risk_free", "pass" if rates is not None else "warn",
                        "13-week T-bill yield present" if rates is not None else "using the fixed 4% fallback",
                        blocks=False))
    return checks
