"""Settings shared by the data refresh, the metrics and the static chart."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

TICKERS = ["AAPL", "MSFT", "GOOGL", "AMZN", "NVDA", "META", "TSLA"]
BENCHMARK = "SPY"            # S&P 500 fund, the comparison line
PORTFOLIO = "M7"             # equal-weight portfolio of the seven, rebalanced daily
RISK_FREE_TICKER = "^IRX"    # 13-week US Treasury bill yield, quoted in percent
START = "2021-11-01"         # first day of the analysis window

TRADING_DAYS = 252
RISK_FREE_FALLBACK = 0.04    # yearly rate used only when the T-bill series is missing

PRICES_CSV = ROOT / "data" / "prices.csv"
RISK_FREE_CSV = ROOT / "data" / "risk_free.csv"
SITE_DATA = ROOT / "site" / "data.json"
CHART_PNG = ROOT / "magnificent_seven_dashboard.png"

LABELS = {PORTFOLIO: "EQ-WT M7", BENCHMARK: "S&P 500"}

# One fixed color per series, the same on the live page (site/index.html) and the PNG.
COLORS = {
    "AAPL": "#3987e5", "MSFT": "#d95926", "GOOGL": "#199e70", "AMZN": "#c98500",
    "NVDA": "#d55181", "META": "#17becf", "TSLA": "#9085e9",
    PORTFOLIO: "#eef1f4", BENCHMARK: "#7d8792",
}


def label(name):
    return LABELS.get(name, name)
