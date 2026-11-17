"""Every number on the dashboard, computed from daily prices.

site/metrics.js computes the same things in the browser so the live page's period
filter works without a server. tests/test_parity.py checks the two agree.
"""

from dataclasses import dataclass

import numpy as np
import pandas as pd

from .config import BENCHMARK, PORTFOLIO, RISK_FREE_FALLBACK, TICKERS, TRADING_DAYS

SERIES = TICKERS + [PORTFOLIO, BENCHMARK]


@dataclass
class Analysis:
    dates: pd.DatetimeIndex     # every day in the period, including the starting day
    returns: pd.DataFrame       # daily returns, one row per day after the first
    growth: pd.DataFrame        # value of $100 invested on the first day
    drawdown: pd.DataFrame      # how far below its running peak each series sits (0 = at a peak)
    metrics: pd.DataFrame       # one row per series: total, cagr, vol, sharpe, maxdd, best, worst
    corr: pd.DataFrame          # correlation of the seven stocks' daily returns
    honesty: pd.DataFrame       # momentum rule vs always guessing "up", per stock
    noise: float                # an edge smaller than this is indistinguishable from luck
    rf_avg: float               # average yearly risk-free rate over the period
    rf_is_fallback: bool


def period_start(dates, years):
    """First date on or after the last date minus `years` calendar years (None = all)."""
    if not years:
        return dates[0]
    cutoff = dates[-1] - pd.DateOffset(years=years)
    return dates[dates >= cutoff][0]


def daily_returns(prices):
    """Simple daily returns for the stocks and benchmark, plus the equal-weight
    portfolio, whose daily return is the average of the seven."""
    returns = prices[TICKERS + [BENCHMARK]].pct_change().iloc[1:]
    returns[PORTFOLIO] = returns[TICKERS].mean(axis=1)
    return returns[SERIES]


def growth_of_100(returns, first_day):
    growth = 100 * (1 + returns).cumprod()
    start = pd.DataFrame(100.0, index=pd.DatetimeIndex([first_day]), columns=returns.columns)
    return pd.concat([start, growth])


def drawdowns(growth):
    return growth / growth.cummax() - 1


def cagr(total_return, days):
    years = days / TRADING_DAYS
    return (1 + total_return) ** (1 / years) - 1


def volatility(returns):
    return returns.std(ddof=1) * np.sqrt(TRADING_DAYS)


def sharpe(returns, rf_daily):
    """Yearly Sharpe ratio: average daily return above the risk-free rate, divided by
    the standard deviation of those excess returns, scaled to a year."""
    excess = returns.sub(rf_daily, axis=0)
    return excess.mean() / excess.std(ddof=1) * np.sqrt(TRADING_DAYS)


def honesty_check(returns):
    """Does "tomorrow goes the way today went" beat simply guessing "up" every day?"""
    up = returns[TICKERS] > 0
    today, tomorrow = up.iloc[:-1].to_numpy(), up.iloc[1:].to_numpy()
    table = pd.DataFrame({
        "always_up": tomorrow.mean(axis=0),
        "momentum": (today == tomorrow).mean(axis=0),
    }, index=TICKERS)
    table["edge"] = table["momentum"] - table["always_up"]
    noise = 2 * np.sqrt(0.25 / len(tomorrow))  # about two standard errors of a 50/50 guess
    return table, noise


def analyze(prices, risk_free=None, start=None):
    """Compute everything for the period starting at `start` (default: all data).

    `risk_free` is the yearly T-bill yield per date (0.05 = 5%), aligned to `prices`.
    Without it, a fixed fallback rate is used.
    """
    if start is not None:
        prices = prices.loc[start:]
    returns = daily_returns(prices)
    growth = growth_of_100(returns, prices.index[0])
    drawdown = drawdowns(growth)

    if risk_free is None:
        rf_daily = pd.Series(RISK_FREE_FALLBACK / TRADING_DAYS, index=returns.index)
    else:
        # The return for day i covers the close of day i-1 to day i; use day i's yield.
        rf_daily = risk_free.reindex(returns.index) / TRADING_DAYS

    total = growth.iloc[-1] / 100 - 1
    metrics = pd.DataFrame({
        "total": total,
        "cagr": cagr(total, len(returns)),
        "vol": volatility(returns),
        "sharpe": sharpe(returns, rf_daily),
        "maxdd": drawdown.min(),
        "best": returns.max(),
        "worst": returns.min(),
    })
    honesty, noise = honesty_check(returns)
    return Analysis(
        dates=prices.index, returns=returns, growth=growth, drawdown=drawdown,
        metrics=metrics, corr=returns[TICKERS].corr(), honesty=honesty, noise=noise,
        rf_avg=float(rf_daily.mean() * TRADING_DAYS), rf_is_fallback=risk_free is None,
    )
