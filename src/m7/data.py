"""Load, check and cache daily prices and the risk-free rate."""

import datetime as dt
import time

import pandas as pd

from .config import BENCHMARK, PRICES_CSV, RISK_FREE_CSV, RISK_FREE_TICKER, START, TICKERS

SERIES = TICKERS + [BENCHMARK]
MARKET_TZ = "America/New_York"
CLOSE_SETTLED = dt.time(16, 30)  # Yahoo's closing prices are final a little after the 4pm close


def download_prices(start=START, attempts=3):
    """Daily adjusted closes from Yahoo Finance, one column per ticker."""
    import yfinance as yf

    # threads=False: yfinance's parallel downloads can collide on its cache file
    # ("database is locked") and silently return one ticker empty.
    for attempt in range(1, attempts + 1):
        raw = yf.download(SERIES, start=start, auto_adjust=True, progress=False, threads=False)
        if not raw.empty:
            close = raw["Close"].reindex(columns=SERIES)
            missing = [t for t in SERIES if close[t].isna().all()]
            if not missing:
                close.index = pd.DatetimeIndex(close.index.date, name="Date")
                return close
            print(f"Download attempt {attempt} returned no data for {', '.join(missing)}.")
        else:
            print(f"Download attempt {attempt} returned no data.")
        time.sleep(10 * attempt)
    raise SystemExit("Could not download prices from Yahoo Finance.")


def download_risk_free(start=START):
    """Yearly T-bill yield (0.05 = 5%) by date, or None if it can't be fetched.

    A failure here shouldn't stop the prices from publishing: the metrics fall
    back to a fixed rate when this is missing.
    """
    try:
        import yfinance as yf

        close = yf.download(RISK_FREE_TICKER, start=start, auto_adjust=False, progress=False)["Close"]
        if isinstance(close, pd.DataFrame):
            close = close.iloc[:, 0]
        close.index = pd.DatetimeIndex(close.index.date, name="Date")
        return (close / 100).rename("risk_free").dropna()
    except Exception as err:  # network errors, Yahoo format changes
        print(f"Risk-free rate download failed ({err}); using the fixed fallback.")
        return None


def drop_unfinished_day(prices, now=None):
    """Leave out today's row until the close has settled, so a run during market
    hours can't publish a mid-day price as that day's close."""
    now = now or pd.Timestamp.now(tz=MARKET_TZ)
    if len(prices) and prices.index[-1].date() == now.date() and now.time() < CLOSE_SETTLED:
        print(f"Dropping {now.date()}: the market hasn't closed yet.")
        return prices.iloc[:-1]
    return prices


def clean_prices(prices):
    """Keep days where every ticker has a price, and refuse data that looks wrong."""
    prices = prices[SERIES].dropna()
    if len(prices) < 250 or (prices <= 0).any().any():
        raise SystemExit("Price data looks wrong (too short or non-positive). Not publishing it.")
    if not prices.index.is_monotonic_increasing or prices.index.has_duplicates:
        raise SystemExit("Price dates are out of order or repeated. Not publishing them.")
    return prices


def align_risk_free(rates, index):
    """One yield per trading day. Bond-market holidays differ from stock-market ones,
    so carry the last known yield forward. Returns None if the series is unusable."""
    if rates is None or rates.empty:
        return None
    aligned = rates.reindex(rates.index.union(index)).ffill().bfill().reindex(index)
    if aligned.isna().any() or not aligned.between(-0.01, 0.25).all():
        print("Risk-free rate data looks wrong; using the fixed fallback.")
        return None
    return aligned.rename("risk_free")


def load_cache():
    prices = pd.read_csv(PRICES_CSV, index_col="Date", parse_dates=True)
    rates = None
    if RISK_FREE_CSV.exists():
        rates = pd.read_csv(RISK_FREE_CSV, index_col="Date", parse_dates=True)["risk_free"]
    return prices, rates


def save_cache(prices, rates):
    PRICES_CSV.parent.mkdir(exist_ok=True)
    prices.to_csv(PRICES_CSV, index_label="Date")
    if rates is not None:
        rates.to_csv(RISK_FREE_CSV, index_label="Date", float_format="%.5f")


def site_payload(prices, rates, updated=None):
    """The data the live page reads. The page computes every metric from this."""
    updated = updated or dt.datetime.now(dt.timezone.utc)
    data = {
        "updated": updated.strftime("%Y-%m-%dT%H:%MZ"),
        "source": "Yahoo Finance, daily adjusted closes",
        "tickers": TICKERS,
        "benchmark": BENCHMARK,
        "dates": [d.strftime("%Y-%m-%d") for d in prices.index],
        "prices": {t: [round(float(v), 4) for v in prices[t]] for t in SERIES},
    }
    if rates is not None:
        data["riskFree"] = [round(float(v), 5) for v in rates]
    return data
