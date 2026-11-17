"""The live page (site/metrics.js) and the Python analysis must report the same numbers.

Runs the page's JavaScript in Node on the same data.json the site publishes, for
every period button, and compares it with src/m7/metrics.py. Skipped if Node
isn't installed (GitHub's runners have it).
"""

import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from m7 import data  # noqa: E402
from m7.config import TICKERS  # noqa: E402
from m7.metrics import analyze, period_start  # noqa: E402

PERIODS = {"1Y": 1, "2Y": 2, "3Y": 3, "MAX": None}
TOLERANCE = 1e-9


@unittest.skipUnless(shutil.which("node"), "Node isn't installed")
class PageMatchesPython(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        prices, rates = data.load_cache()
        rates = data.align_risk_free(rates, prices.index)
        payload = data.site_payload(prices, rates)
        # Analyze exactly what the page sees: the rounded prices and yields in data.json.
        cls.prices = pd.DataFrame(payload["prices"], index=pd.DatetimeIndex(payload["dates"]))
        cls.rates = pd.Series(payload["riskFree"], index=cls.prices.index)
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "data.json"
            path.write_text(json.dumps(payload))
            run = subprocess.run(["node", str(ROOT / "tests" / "js_compute.js"), str(path)],
                                 capture_output=True, text=True, check=True)
        cls.js = json.loads(run.stdout)

    def test_every_period_and_metric(self):
        for name, years in PERIODS.items():
            js = self.js[name]
            start = period_start(self.prices.index, years)
            a = analyze(self.prices, self.rates, start=start)
            with self.subTest(period=name):
                self.assertEqual(js["start"], start.strftime("%Y-%m-%d"))
                self.assertEqual(js["days"], len(a.returns))
                self.assertAlmostEqual(js["noise"], a.noise, delta=TOLERANCE)
                self.assertAlmostEqual(js["rfAvg"], a.rf_avg, delta=TOLERANCE)
                for series, row in a.metrics.iterrows():
                    for metric, value in row.items():
                        self.assertAlmostEqual(js["metrics"][series][metric], value, delta=TOLERANCE,
                                               msg=f"{name} {series} {metric}")
                    self.assertAlmostEqual(js["growthEnd"][series], a.growth[series].iloc[-1], delta=1e-6)
                for i, t1 in enumerate(TICKERS):
                    for j, t2 in enumerate(TICKERS):
                        self.assertAlmostEqual(js["corr"][i][j], a.corr.loc[t1, t2], delta=TOLERANCE)
                    self.assertAlmostEqual(js["honesty"][t1]["alwaysUp"], a.honesty.loc[t1, "always_up"])
                    self.assertAlmostEqual(js["honesty"][t1]["momentum"], a.honesty.loc[t1, "momentum"])


if __name__ == "__main__":
    unittest.main()
