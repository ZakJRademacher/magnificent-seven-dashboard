"""Metric definitions, checked against small hand-worked examples."""

import math
import sys
import unittest
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from m7 import metrics  # noqa: E402
from m7.config import BENCHMARK, PORTFOLIO, TICKERS, TRADING_DAYS  # noqa: E402


def frame(columns, start="2024-01-01"):
    """Prices for every series. Unlisted tickers stay flat at 100."""
    n = len(next(iter(columns.values())))
    dates = pd.bdate_range(start, periods=n)
    data = {t: columns.get(t, [100.0] * n) for t in TICKERS + [BENCHMARK]}
    return pd.DataFrame(data, index=dates)


class ReturnsAndGrowth(unittest.TestCase):
    def setUp(self):
        self.prices = frame({"AAPL": [100, 110, 99, 99], "MSFT": [50, 50, 55, 44]})
        self.a = metrics.analyze(self.prices, risk_free=pd.Series(0.0, index=self.prices.index))

    def test_daily_returns(self):
        self.assertEqual(self.a.returns["AAPL"].round(10).tolist(), [0.1, -0.1, 0.0])
        self.assertEqual(self.a.returns["MSFT"].round(10).tolist(), [0.0, 0.1, -0.2])

    def test_portfolio_is_daily_average_of_the_seven(self):
        # Day 1: AAPL +10%, others flat -> 10% / 7. Day 2: AAPL -10%, MSFT +10% -> 0.
        # Day 3: MSFT -20% -> -20% / 7.
        expected = [0.1 / 7, 0.0, -0.2 / 7]
        np.testing.assert_allclose(self.a.returns[PORTFOLIO], expected, atol=1e-15)

    def test_growth_starts_at_100_on_the_first_day(self):
        self.assertEqual(self.a.growth.index[0], self.prices.index[0])
        np.testing.assert_allclose(self.a.growth["AAPL"], [100, 110, 99, 99])
        np.testing.assert_allclose(self.a.growth["MSFT"], [100, 100, 110, 88])

    def test_drawdown_from_running_peak(self):
        np.testing.assert_allclose(self.a.drawdown["AAPL"], [0, 0, -0.1, -0.1])
        np.testing.assert_allclose(self.a.drawdown["MSFT"], [0, 0, 0, -0.2])
        self.assertAlmostEqual(self.a.metrics.loc["MSFT", "maxdd"], -0.2)

    def test_total_best_and_worst_day(self):
        m = self.a.metrics.loc["AAPL"]
        self.assertAlmostEqual(m["total"], -0.01)
        self.assertAlmostEqual(m["best"], 0.1)
        self.assertAlmostEqual(m["worst"], -0.1)

    def test_cagr_compounds_over_trading_years(self):
        # 3 return days = 3/252 of a year, so -1% over that span annualizes to 0.99 ** 84 - 1.
        self.assertAlmostEqual(self.a.metrics.loc["AAPL", "cagr"], 0.99 ** (TRADING_DAYS / 3) - 1)

    def test_volatility_is_sample_std_scaled_to_a_year(self):
        r = [0.1, -0.1, 0.0]
        expected = np.std(r, ddof=1) * math.sqrt(TRADING_DAYS)  # = 0.1 * sqrt(252)
        self.assertAlmostEqual(self.a.metrics.loc["AAPL", "vol"], expected)
        self.assertAlmostEqual(expected, 0.1 * math.sqrt(252))

    def test_flat_series_has_no_drawdown(self):
        self.assertEqual(self.a.metrics.loc["GOOGL", "maxdd"], 0)
        self.assertEqual(self.a.metrics.loc["GOOGL", "total"], 0)


class Sharpe(unittest.TestCase):
    def test_excess_return_over_its_own_volatility(self):
        r = pd.Series([0.02, -0.01, 0.03, 0.0])
        rf = pd.Series([0.01, 0.01, 0.01, 0.01])
        excess = r - rf  # 0.01, -0.02, 0.02, -0.01 -> mean 0
        self.assertAlmostEqual(metrics.sharpe(r.to_frame("x"), rf)["x"], 0.0)
        r2 = pd.Series([0.03, 0.01, 0.02, 0.02])
        excess = r2 - rf  # 0.02, 0.00, 0.01, 0.01
        expected = excess.mean() / excess.std(ddof=1) * math.sqrt(252)
        self.assertAlmostEqual(metrics.sharpe(r2.to_frame("x"), rf)["x"], expected)

    def test_uses_each_days_risk_free_yield(self):
        prices = frame({"AAPL": [100, 101, 103, 102, 104]})
        low = metrics.analyze(prices, pd.Series(0.0, index=prices.index))
        high = metrics.analyze(prices, pd.Series(0.05, index=prices.index))
        self.assertGreater(low.metrics.loc["AAPL", "sharpe"], high.metrics.loc["AAPL", "sharpe"])
        self.assertAlmostEqual(high.rf_avg, 0.05)
        self.assertFalse(high.rf_is_fallback)

    def test_falls_back_to_fixed_rate_without_a_series(self):
        prices = frame({"AAPL": [100, 101, 103, 102, 104]})
        a = metrics.analyze(prices)
        self.assertTrue(a.rf_is_fallback)
        self.assertAlmostEqual(a.rf_avg, 0.04)

    def test_negative_cagr_can_still_have_positive_sharpe(self):
        # Big swings: the average daily return is positive while the compounded result is a loss.
        # This is why TSLA shows a negative CAGR but a positive Sharpe ratio.
        prices = frame({"TSLA": [100, 150, 75, 112.5, 56.25 * 1.7]})
        a = metrics.analyze(prices, pd.Series(0.0, index=prices.index))
        self.assertLess(a.metrics.loc["TSLA", "total"], 0)
        self.assertGreater(a.metrics.loc["TSLA", "sharpe"], 0)


class Correlation(unittest.TestCase):
    def test_same_and_opposite_moves(self):
        moves = [100, 102, 101, 104, 103, 107]
        mirror = [100, 98, 99, 96, 97, 93]
        prices = frame({"AAPL": moves, "MSFT": [m * 2 for m in moves], "GOOGL": mirror})
        a = metrics.analyze(prices)
        self.assertAlmostEqual(a.corr.loc["AAPL", "MSFT"], 1.0)
        self.assertLess(a.corr.loc["AAPL", "GOOGL"], -0.99)
        np.testing.assert_allclose(np.diag(a.corr.loc[["AAPL", "MSFT"], ["AAPL", "MSFT"]]), [1, 1])


class HonestyCheck(unittest.TestCase):
    def test_counts_against_hand_worked_example(self):
        # AAPL up/down pattern over 5 return days: U U D D U
        prices = frame({"AAPL": [100, 101, 102, 101, 100, 101]})
        a = metrics.analyze(prices)
        row = a.honesty.loc["AAPL"]
        # Next-day outcomes (days 2-5): U D D U -> "always up" right 2 of 4.
        self.assertAlmostEqual(row["always_up"], 0.5)
        # Same as previous day? U=U yes, D!=U no, D=D yes, U!=D no -> 2 of 4.
        self.assertAlmostEqual(row["momentum"], 0.5)
        self.assertAlmostEqual(row["edge"], 0.0)
        self.assertAlmostEqual(a.noise, 2 * math.sqrt(0.25 / 4))

    def test_flat_day_counts_as_not_up(self):
        prices = frame({"AAPL": [100, 101, 101, 102]})  # U, flat, U
        row = metrics.analyze(prices).honesty.loc["AAPL"]
        self.assertAlmostEqual(row["always_up"], 0.5)
        self.assertAlmostEqual(row["momentum"], 0.0)


class Periods(unittest.TestCase):
    def test_period_start_is_first_day_on_or_after_the_cutoff(self):
        dates = pd.DatetimeIndex(["2023-11-15", "2023-11-17", "2024-06-03", "2024-11-15"])
        self.assertEqual(metrics.period_start(dates, 1), pd.Timestamp("2023-11-15"))
        dates = pd.DatetimeIndex(["2023-11-14", "2023-11-16", "2024-06-03", "2024-11-15"])
        self.assertEqual(metrics.period_start(dates, 1), pd.Timestamp("2023-11-16"))
        self.assertEqual(metrics.period_start(dates, None), dates[0])

    def test_analyze_from_a_start_date_resets_growth(self):
        prices = frame({"AAPL": [100, 110, 121, 133.1]})
        a = metrics.analyze(prices, start=prices.index[1])
        np.testing.assert_allclose(a.growth["AAPL"], [100, 110, 121])
        self.assertEqual(len(a.returns), 2)


if __name__ == "__main__":
    unittest.main()
