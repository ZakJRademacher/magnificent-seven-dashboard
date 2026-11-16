# Magnificent Seven Dashboard

A one-page risk and return dashboard for the seven largest US tech stocks (Apple, Microsoft, Alphabet, Amazon, Nvidia, Meta, Tesla), compared with the S&P 500.

![Magnificent Seven dashboard](magnificent_seven_dashboard.png)

## What it answers

- How much did each stock grow, and how does an equal-weight portfolio of all seven compare with the S&P 500?
- How risky was the ride (volatility, Sharpe ratio, drawdowns)?
- Do the seven actually diversify each other, or do they move together?
- Does a simple "momentum" signal beat the dumb baseline of always guessing "up"?

## How to run it

1. Install the requirements: `pip install -r requirements.txt`
2. Open `magnificent_seven_dashboard.ipynb` in JupyterLab and run all cells.

The notebook reads prices from `m7_prices.csv` if it exists. To pull fresh prices from Yahoo Finance, set `REFRESH = True` in the first code cell. Tickers, start date, benchmark and risk-free rate are set in the same cell.

## Files

| File | What it is |
|---|---|
| `magnificent_seven_dashboard.ipynb` | The analysis: load, check, compute, chart, honesty check |
| `m7_prices.csv` | Cached daily adjusted closes from Yahoo Finance (Nov 1, 2021 to Nov 16, 2026) |
| `magnificent_seven_dashboard.png` | The dashboard image the notebook produces |
| `requirements.txt` | Python packages used |

## Method notes

- Prices are adjusted for splits and dividends.
- The equal-weight portfolio holds one-seventh in each stock and rebalances daily.
- Sharpe ratio uses a 4% yearly risk-free rate.
- Volatility is the standard deviation of daily returns, scaled to a year (252 trading days).

## Limits

- The seven were picked because they won, so looking back overstates what choosing in advance would have earned (survivorship bias).
- Results depend on the start date.
- This is analysis practice, not investment advice.

## Stack

Python, pandas, NumPy, Matplotlib, yfinance, JupyterLab
