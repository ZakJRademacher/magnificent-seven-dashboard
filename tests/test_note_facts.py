"""The daily note's fact sheet, checked against small hand-worked examples and the cached history."""

import sys
import unittest
from decimal import Decimal
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from m7.config import BENCHMARK, PRICES_CSV, TICKERS  # noqa: E402
from m7.note.facts import build_facts, shown  # noqa: E402

# Eight sessions spanning a year end: Dec 24, 25, 26, 27, 30, 31, Jan 1, Jan 2.
DATES = pd.bdate_range("2024-12-24", periods=8)


def frame(columns):
    """Prices for every series over DATES. Unlisted series stay flat at 100."""
    data = {t: columns.get(t, [100.0] * len(DATES)) for t in TICKERS + [BENCHMARK]}
    return pd.DataFrame(data, index=DATES)


FLAT6 = [100.0] * 6
PRICES = frame({
    "AAPL": FLAT6 + [110.0, 121.0],   # Jan 1: +10%; Jan 2: +10% (121 / 110)
    "MSFT": FLAT6 + [100.0, 95.0],    # Jan 2: -5%
    BENCHMARK: FLAT6 + [100.0, 100.5],  # Jan 2: +0.5%
})


class Rounding(unittest.TestCase):
    def test_one_decimal_place_halves_away_from_zero(self):
        self.assertEqual(shown(0.04236), Decimal("4.2"))
        self.assertEqual(shown(0.0005), Decimal("0.1"))
        self.assertEqual(shown(-0.0005), Decimal("-0.1"))
        self.assertEqual(shown(0.00049), Decimal("0.0"))

    def test_float_noise_does_not_change_the_shown_value(self):
        self.assertEqual(shown(110 / 100 - 1), Decimal("10.0"))  # 0.10000000000000009

    def test_exact_halves_from_real_prices_still_round_away_from_zero(self):
        # 100.05 / 100 - 1 is 0.000499999... in floats; it is exactly half of 0.1%.
        self.assertEqual(shown(100.05 / 100 - 1), Decimal("0.1"))
        self.assertEqual(shown(99.95 / 100 - 1), Decimal("-0.1"))

    def test_a_price_half_a_tenth_of_a_percent_up_is_not_flat(self):
        p = frame({"AAPL": FLAT6 + [100.0, 100.05], "MSFT": FLAT6 + [100.0, 99.95]})
        s = build_facts(p, "2025-01-02")
        self.assertEqual(s["facts"]["AAPL.move_1d"]["text"], "Apple rose 0.1%")
        self.assertEqual(s["facts"]["MSFT.move_1d"]["text"], "Microsoft fell 0.1%")


class HandWorkedDay(unittest.TestCase):
    """Jan 2: AAPL +10%, MSFT -5%, the other five flat, SPY +0.5%."""

    def setUp(self):
        self.s = build_facts(PRICES, "2025-01-02")
        self.f = self.s["facts"]

    def test_baseline_dates(self):
        self.assertEqual(self.s["previous_session"], "2025-01-01")
        self.assertEqual(self.s["five_sessions_back"], "2024-12-26")
        self.assertEqual(self.s["previous_year_end"], "2024-12-31")

    def test_one_day_moves(self):
        self.assertAlmostEqual(self.f["AAPL.change_1d"]["value"], 0.10, places=12)
        self.assertEqual(self.f["AAPL.move_1d"]["text"], "Apple rose 10.0%")
        self.assertEqual(self.f["MSFT.move_1d"]["text"], "Microsoft fell 5.0%")
        self.assertEqual(self.f["GOOGL.move_1d"]["text"], "Alphabet was flat")
        self.assertEqual(self.f["SPY.move_1d"]["text"], "the S&P 500 fund (SPY) rose 0.5%")

    def test_five_day_and_year_to_date(self):
        # Both baselines are 100 (Dec 26 and Dec 31), so 121 / 100 - 1 = 21%.
        self.assertAlmostEqual(self.f["AAPL.change_5d"]["value"], 0.21, places=12)
        self.assertEqual(self.f["AAPL.change_5d"]["text"], "up 21.0% over five trading days")
        self.assertEqual(self.f["AAPL.change_ytd"]["text"], "up 21.0% so far in 2025")
        self.assertEqual(self.f["MSFT.change_ytd"]["text"], "down 5.0% so far in 2025")
        self.assertEqual(self.f["TSLA.change_ytd"]["text"], "unchanged so far in 2025")

    def test_group_is_the_simple_average_and_the_gap_is_in_points(self):
        # (+10% - 5% + 5 x 0%) / 7 = 0.714...%; minus SPY's 0.5% = 0.214... points.
        self.assertAlmostEqual(self.f["group.move_1d"]["value"], 0.05 / 7, places=12)
        self.assertEqual(self.f["group.move_1d"]["text"], "the seven stocks rose 0.7% on average")
        self.assertAlmostEqual(self.f["group.gap_to_spy_1d"]["value"], 0.05 / 7 - 0.005, places=12)
        self.assertEqual(self.f["group.gap_to_spy_1d"]["text"],
                         "0.2 percentage points ahead of the S&P 500 fund (SPY)")

    def test_counts_and_claims(self):
        c = self.s["claims"]
        self.assertEqual((c["up"], c["down"]), (["AAPL"], ["MSFT"]))
        self.assertEqual(len(c["flat"]), 5)
        self.assertEqual(self.f["count.up"]["text"], "1 of the seven rose")
        self.assertEqual(self.f["count.flat"]["text"], "5 of the seven were flat")
        self.assertEqual(c["best_1d"], ["AAPL"])
        self.assertEqual(c["worst_1d"], ["MSFT"])
        self.assertEqual(c["biggest_mover_1d"], ["AAPL"])
        self.assertFalse(c["all_up"] or c["all_down"])
        self.assertTrue(c["group_beat_spy"])

    def test_closes_and_date(self):
        self.assertEqual(self.f["AAPL.close"]["text"], "$121.00")
        self.assertEqual(self.f["date"]["text"], "Thursday, January 2, 2025")


class Edges(unittest.TestCase):
    def test_first_session_of_the_year_counts_its_own_move(self):
        f = build_facts(PRICES, "2025-01-01")["facts"]
        self.assertAlmostEqual(f["AAPL.change_ytd"]["value"], 0.10, places=12)
        self.assertAlmostEqual(f["AAPL.change_1d"]["value"], 0.10, places=12)

    def test_missing_baselines_are_left_out(self):
        s = build_facts(PRICES, "2024-12-27")  # only three earlier sessions, none from 2023
        self.assertIsNone(s["five_sessions_back"])
        self.assertIsNone(s["previous_year_end"])
        self.assertNotIn("AAPL.change_5d", s["facts"])
        self.assertNotIn("AAPL.change_ytd", s["facts"])

    def test_ties_compare_the_shown_values(self):
        p = frame({"AAPL": FLAT6 + [100.0, 102.0], "NVDA": FLAT6 + [50.0, 51.0], "TSLA": FLAT6 + [100.0, 98.0]})
        c = build_facts(p, "2025-01-02")["claims"]
        self.assertEqual(c["best_1d"], ["AAPL", "NVDA"])
        self.assertEqual(c["biggest_mover_1d"], ["AAPL", "NVDA", "TSLA"])  # +2.0, +2.0 and -2.0

    def test_tiny_moves_count_as_flat_in_either_direction(self):
        p = frame({"AAPL": FLAT6 + [100.0, 100.04], "MSFT": FLAT6 + [100.0, 99.96]})
        s = build_facts(p, "2025-01-02")
        self.assertIn("AAPL", s["claims"]["flat"])
        self.assertIn("MSFT", s["claims"]["flat"])
        self.assertEqual(s["facts"]["MSFT.move_1d"]["text"], "Microsoft was flat")

    def test_all_up(self):
        p = frame({t: FLAT6 + [100.0, 101.0] for t in TICKERS})
        s = build_facts(p, "2025-01-02")
        self.assertTrue(s["claims"]["all_up"])
        self.assertEqual(len(s["claims"]["best_1d"]), 7)
        self.assertEqual(s["facts"]["count.up"]["text"], "all seven rose")
        self.assertEqual(s["facts"]["count.down"]["text"], "none of the seven fell")
        self.assertEqual(s["facts"]["count.flat"]["text"], "none of the seven was flat")

    def test_rejects_dates_without_a_comparison(self):
        with self.assertRaises(ValueError):
            build_facts(PRICES, "2024-12-24")  # first session in the history
        with self.assertRaises(ValueError):
            build_facts(PRICES, "2025-01-04")  # not a trading day here

    def test_hash_changes_only_when_a_figure_changes(self):
        a = build_facts(PRICES, "2025-01-02")["hash"]
        self.assertEqual(a, build_facts(PRICES.copy(), "2025-01-02")["hash"])
        changed = PRICES.copy()
        changed.loc["2025-01-02", "AAPL"] = 121.5
        self.assertNotEqual(a, build_facts(changed, "2025-01-02")["hash"])

    def test_rounding_noise_between_downloads_keeps_the_hash(self):
        # Yahoo's adjusted closes differ by up to about 1e-5 between downloads; the wording doesn't change.
        a = build_facts(PRICES, "2025-01-02")["hash"]
        noisy = PRICES.copy()
        noisy.loc["2025-01-02", "AAPL"] *= 1 + 1e-6
        self.assertEqual(a, build_facts(noisy, "2025-01-02")["hash"])


class CachedHistory(unittest.TestCase):
    """The fact sheet for the latest cached day agrees with a direct calculation from the CSV."""

    def test_latest_day_matches_direct_calculation(self):
        prices = pd.read_csv(PRICES_CSV, index_col="Date", parse_dates=True)
        s = build_facts(prices)
        last, prev = prices.index[-1], prices.index[-2]
        year_end = prices.index[prices.index.year == last.year - 1][-1]
        for t in TICKERS + [BENCHMARK]:
            self.assertAlmostEqual(s["facts"][f"{t}.change_1d"]["value"],
                                   prices.at[last, t] / prices.at[prev, t] - 1, places=12)
            self.assertAlmostEqual(s["facts"][f"{t}.change_5d"]["value"],
                                   prices.at[last, t] / prices.iloc[-6][t] - 1, places=12)
            self.assertAlmostEqual(s["facts"][f"{t}.change_ytd"]["value"],
                                   prices.at[last, t] / prices.at[year_end, t] - 1, places=12)
        daily = prices[TICKERS].pct_change().iloc[-1]
        self.assertAlmostEqual(s["facts"]["group.move_1d"]["value"], daily.mean(), places=12)


if __name__ == "__main__":
    unittest.main()
