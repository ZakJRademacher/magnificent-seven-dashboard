"""Refresh the price data behind the live dashboard.

Downloads daily adjusted closes for the Magnificent Seven and SPY from
Yahoo Finance, plus the 13-week US Treasury bill yield used as the
risk-free rate, and writes them to site/data.json, which site/index.html
reads in the browser. Runs every weekday on GitHub Actions; you can also
run it yourself to preview the site locally.

    python update_data.py              # download fresh prices
    python update_data.py --from-csv   # reuse m7_prices.csv (works offline)
"""

import argparse
import datetime as dt
import json
import time
from pathlib import Path

import pandas as pd

TICKERS = ["AAPL", "MSFT", "GOOGL", "AMZN", "NVDA", "META", "TSLA"]
BENCHMARK = "SPY"
RISK_FREE = "^IRX"  # 13-week US Treasury bill yield, quoted in percent
START = "2021-11-01"
CSV = Path("m7_prices.csv")
OUT = Path("site/data.json")
MARKET_TZ = "America/New_York"
CLOSE_SETTLED = dt.time(16, 30)  # Yahoo's closing prices are final a little after the 4pm close


def download(tickers, start, attempts=3):
    # Yahoo sometimes refuses a request, so try a few times before giving up.
    import yfinance as yf

    # threads=False: yfinance's parallel downloads can collide on its cache file
    # ("database is locked") and silently return one ticker empty.
    for attempt in range(1, attempts + 1):
        raw = yf.download(tickers, start=start, auto_adjust=True, progress=False, threads=False)
        if not raw.empty:
            close = raw["Close"].reindex(columns=tickers)
            missing = [t for t in tickers if close[t].isna().all()]
            if not missing:
                return close
            print(f"Download attempt {attempt} returned no data for {', '.join(missing)}.")
        else:
            print(f"Download attempt {attempt} returned no data.")
        time.sleep(10 * attempt)
    raise SystemExit("Could not download prices from Yahoo Finance.")


def risk_free_rates(index, start):
    """Yearly T-bill yield (0.05 = 5%) for each trading day, or None if it can't be fetched.

    The page falls back to a fixed rate when this is missing, so a failure here
    shouldn't stop the prices from publishing.
    """
    try:
        import yfinance as yf

        close = yf.download(RISK_FREE, start=start, auto_adjust=False, progress=False)["Close"]
        if isinstance(close, pd.DataFrame):
            close = close.iloc[:, 0]
        # Bond-market holidays differ from stock-market ones, so carry the last known yield forward.
        rates = (close / 100).reindex(index).ffill().bfill()
    except Exception as err:  # network errors, Yahoo format changes
        print(f"Risk-free rate download failed ({err}); the page will use its fixed fallback.")
        return None
    if rates.isna().any() or not rates.between(-0.01, 0.25).all():
        print("Risk-free rate data looks wrong; the page will use its fixed fallback.")
        return None
    return rates


def drop_unfinished_day(prices):
    # A run during market hours would otherwise publish a mid-day price as that day's close.
    now = pd.Timestamp.now(tz=MARKET_TZ)
    if len(prices) and prices.index[-1].date() == now.date() and now.time() < CLOSE_SETTLED:
        print(f"Dropping {now.date()}: the market hasn't closed yet.")
        return prices.iloc[:-1]
    return prices


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--from-csv", action="store_true", help="use m7_prices.csv instead of downloading")
    args = parser.parse_args()

    tickers = TICKERS + [BENCHMARK]
    if args.from_csv:
        prices = pd.read_csv(CSV, index_col=0, parse_dates=True)[tickers]
    else:
        prices = download(tickers, START)

    # Keep only days where every ticker has a price, so comparisons are like-for-like.
    prices = prices.dropna()
    if not args.from_csv:
        prices = drop_unfinished_day(prices)
    if len(prices) < 250 or (prices <= 0).any().any():
        raise SystemExit("Price data looks wrong (too short or non-positive). Not publishing it.")

    rates = None if args.from_csv else risk_free_rates(prices.index, START)

    data = {
        "updated": dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%MZ"),
        "source": "Yahoo Finance, daily adjusted closes",
        "tickers": TICKERS,
        "benchmark": BENCHMARK,
        "dates": [d.strftime("%Y-%m-%d") for d in prices.index],
        "prices": {t: [round(float(v), 4) for v in prices[t]] for t in tickers},
    }
    if rates is not None:
        data["riskFree"] = [round(float(v), 5) for v in rates]
    OUT.parent.mkdir(exist_ok=True)
    OUT.write_text(json.dumps(data, separators=(",", ":")))
    rf_note = f"T-bill yield {rates.iloc[-1]:.2%} latest" if rates is not None else "no risk-free series"
    print(f"Wrote {OUT}: {len(prices):,} days, {data['dates'][0]} to {data['dates'][-1]}, {rf_note}")


if __name__ == "__main__":
    main()
