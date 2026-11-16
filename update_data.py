"""Refresh the price data behind the live dashboard.

Downloads daily adjusted closes for the Magnificent Seven and SPY from
Yahoo Finance and writes them to site/data.json, which site/index.html
reads in the browser. Runs every weekday on GitHub Actions; you can also
run it yourself to preview the site locally.

    python update_data.py              # download fresh prices
    python update_data.py --from-csv   # reuse m7_prices.csv (works offline)
"""

import argparse
import json
import time
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

TICKERS = ["AAPL", "MSFT", "GOOGL", "AMZN", "NVDA", "META", "TSLA"]
BENCHMARK = "SPY"
START = "2021-11-01"
CSV = Path("m7_prices.csv")
OUT = Path("site/data.json")


def download(tickers, start, attempts=3):
    # Yahoo sometimes refuses a request, so try a few times before giving up.
    import yfinance as yf

    for attempt in range(1, attempts + 1):
        raw = yf.download(tickers, start=start, auto_adjust=True, progress=False)
        if not raw.empty:
            return raw["Close"][tickers]
        print(f"Download attempt {attempt} returned no data.")
        time.sleep(10 * attempt)
    raise SystemExit("Could not download prices from Yahoo Finance.")


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
    if len(prices) < 250 or (prices <= 0).any().any():
        raise SystemExit("Price data looks wrong (too short or non-positive). Not publishing it.")

    data = {
        "updated": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%MZ"),
        "source": "Yahoo Finance, daily adjusted closes",
        "tickers": TICKERS,
        "benchmark": BENCHMARK,
        "dates": [d.strftime("%Y-%m-%d") for d in prices.index],
        "prices": {t: [round(float(v), 4) for v in prices[t]] for t in tickers},
    }
    OUT.parent.mkdir(exist_ok=True)
    OUT.write_text(json.dumps(data, separators=(",", ":")))
    print(f"Wrote {OUT}: {len(prices):,} days, {data['dates'][0]} to {data['dates'][-1]}")


if __name__ == "__main__":
    main()
