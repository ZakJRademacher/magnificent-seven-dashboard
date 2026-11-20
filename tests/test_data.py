"""Data guards, the cached data, and a fixed snapshot of published figures."""

import sys
import unittest
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from m7 import data  # noqa: E402
from m7.config import TICKERS  # noqa: E402
from m7.metrics import analyze  # noqa: E402

SNAPSHOT_END = "2026-11-16"  # the cache can grow; this snapshot stays fixed


def prices_for(dates, value=100.0):
    return pd.DataFrame(value, index=pd.DatetimeIndex(dates), columns=data.SERIES)


class UnfinishedDay(unittest.TestCase):
    def setUp(self):
        self.prices = prices_for(["2026-11-13", "2026-11-16"])

    def ny(self, when):
        return pd.Timestamp(when, tz=data.MARKET_TZ)

    def test_drops_today_before_the_close_settles(self):
        out = data.drop_unfinished_day(self.prices, now=self.ny("2026-11-16 15:59"))
        self.assertEqual(out.index[-1], pd.Timestamp("2026-11-13"))

    def test_keeps_today_after_the_close(self):
        out = data.drop_unfinished_day(self.prices, now=self.ny("2026-11-16 16:30"))
        self.assertEqual(len(out), 2)

    def test_keeps_earlier_days_and_empty_frames(self):
        self.assertEqual(len(data.drop_unfinished_day(self.prices, now=self.ny("2026-11-17 10:00"))), 2)
        self.assertEqual(len(data.drop_unfinished_day(self.prices.iloc[:0], now=self.ny("2026-11-16 10:00"))), 0)


class CleanPrices(unittest.TestCase):
    def test_drops_incomplete_days(self):
        p = prices_for(pd.bdate_range("2024-01-01", periods=300))
        p.iloc[5, 0] = None
        self.assertEqual(len(data.clean_prices(p)), 299)

    def test_refuses_short_or_non_positive_data(self):
        with self.assertRaises(SystemExit):
            data.clean_prices(prices_for(pd.bdate_range("2024-01-01", periods=100)))
        p = prices_for(pd.bdate_range("2024-01-01", periods=300))
        p.iloc[10, 2] = 0
        with self.assertRaises(SystemExit):
            data.clean_prices(p)


class RiskFree(unittest.TestCase):
    def test_carries_yield_over_bond_market_holidays(self):
        index = pd.DatetimeIndex(["2026-11-10", "2026-11-11", "2026-11-12"])
        rates = pd.Series([0.041, 0.042], index=pd.DatetimeIndex(["2026-11-10", "2026-11-12"]))
        aligned = data.align_risk_free(rates, index)
        self.assertEqual(aligned.tolist(), [0.041, 0.041, 0.042])

    def test_rejects_implausible_yields(self):
        index = pd.DatetimeIndex(["2026-11-10"])
        self.assertIsNone(data.align_risk_free(pd.Series([4.1], index=index), index))  # percent, not decimal
        self.assertIsNone(data.align_risk_free(None, index))


class CachedData(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.prices, cls.rates = data.load_cache()

    def test_cache_is_complete_and_positive(self):
        self.assertEqual(list(self.prices.columns), data.SERIES)
        self.assertFalse(self.prices.isna().any().any())
        self.assertTrue((self.prices > 0).all().all())
        self.assertTrue(self.prices.index.is_monotonic_increasing)
        self.assertGreaterEqual(len(self.prices), 1266)

    def test_risk_free_covers_every_trading_day(self):
        aligned = data.align_risk_free(self.rates, self.prices.index)
        self.assertIsNotNone(aligned)
        self.assertTrue(aligned.between(0, 0.06).all())

    def test_site_payload_matches_the_page_contract(self):
        payload = data.site_payload(self.prices, data.align_risk_free(self.rates, self.prices.index))
        self.assertEqual(payload["tickers"], TICKERS)
        self.assertEqual(payload["benchmark"], "SPY")
        n = len(payload["dates"])
        self.assertTrue(all(len(v) == n for v in payload["prices"].values()))
        self.assertEqual(len(payload["riskFree"]), n)


class PublishedSnapshot(unittest.TestCase):
    """Figures from the dashboard as published for Nov 1, 2021 to Nov 16, 2026."""

    @classmethod
    def setUpClass(cls):
        prices, rates = data.load_cache()
        prices = prices.loc[:SNAPSHOT_END]
        cls.a = analyze(prices, data.align_risk_free(rates, prices.index))

    def test_period(self):
        self.assertEqual(len(self.a.returns), 1265)
        self.assertAlmostEqual(self.a.rf_avg, 0.038, places=3)

    def test_headline_figures(self):
        m = self.a.metrics.round(3)
        expected = {  # total, cagr, vol, sharpe, maxdd
            "AAPL": (1.430, 0.193, 0.281, 0.63, -0.334),
            "NVDA": (5.072, 0.432, 0.521, 0.87, -0.663),
            "TSLA": (-0.057, -0.012, 0.597, 0.21, -0.736),
            "M7": (1.494, 0.200, 0.302, 0.63, -0.494),
            "SPY": (0.720, 0.114, 0.173, 0.49, -0.245),
        }
        for name, (total, cagr, vol, sharpe, maxdd) in expected.items():
            with self.subTest(name):
                self.assertAlmostEqual(m.loc[name, "total"], total, places=3)
                self.assertAlmostEqual(m.loc[name, "cagr"], cagr, places=3)
                self.assertAlmostEqual(m.loc[name, "vol"], vol, places=3)
                self.assertAlmostEqual(round(self.a.metrics.loc[name, "sharpe"], 2), sharpe, places=2)
                self.assertAlmostEqual(m.loc[name, "maxdd"], maxdd, places=3)

    def test_no_stock_beats_the_luck_threshold(self):
        self.assertAlmostEqual(self.a.noise, 0.028, places=3)
        self.assertTrue((self.a.honesty["edge"] <= self.a.noise).all())


if __name__ == "__main__":
    unittest.main()


class Version(unittest.TestCase):
    def test_the_page_shows_the_package_version(self):
        import m7
        page = (Path(__file__).resolve().parents[1] / "site" / "index.html").read_text(encoding="utf-8")
        self.assertIn(f'<span id="version">v{m7.__version__}</span>', page)
