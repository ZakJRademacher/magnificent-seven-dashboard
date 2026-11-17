"""Refresh the Magnificent Seven dashboard.

    python refresh.py               download fresh prices, update data/, site/data.json and the PNG
    python refresh.py --offline     rebuild from the cached data in data/ (no network)
    python refresh.py --no-chart    skip the PNG (the live-site build uses this)

The live page (site/index.html) computes its metrics in the browser from
site/data.json. This script prints the same metrics for the full period.
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))

from m7 import data  # noqa: E402
from m7.config import CHART_PNG, SITE_DATA, label  # noqa: E402
from m7.metrics import analyze  # noqa: E402


def refresh(offline=False, chart=True):
    if offline:
        prices, rates = data.load_cache()
    else:
        prices = data.drop_unfinished_day(data.download_prices())
        rates = data.download_risk_free()
    prices = data.clean_prices(prices)
    rates = data.align_risk_free(rates, prices.index)
    if not offline:
        data.save_cache(prices, rates)

    SITE_DATA.parent.mkdir(exist_ok=True)
    import json
    SITE_DATA.write_text(json.dumps(data.site_payload(prices, rates), separators=(",", ":")))

    analysis = analyze(prices, rates)
    print(f"Wrote {SITE_DATA.relative_to(SITE_DATA.parents[1])}: {len(prices):,} days, "
          f"{prices.index[0]:%Y-%m-%d} to {prices.index[-1]:%Y-%m-%d}, "
          + ("fixed risk-free rate" if rates is None else f"T-bill yield {rates.iloc[-1]:.2%} latest"))
    table = analysis.metrics.rename(index=label)
    formats = {c: "{:+.1%}".format for c in table.columns}
    formats.update(vol="{:.1%}".format, sharpe="{:.2f}".format)
    print(table.to_string(formatters=formats))

    if chart:
        from m7.chart import render
        render(analysis, CHART_PNG)
        print(f"Wrote {CHART_PNG.name}")
    return analysis


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--offline", action="store_true", help="use the cached data in data/")
    parser.add_argument("--no-chart", action="store_true", help="don't render the PNG")
    args = parser.parse_args()
    refresh(offline=args.offline, chart=not args.no_chart)
