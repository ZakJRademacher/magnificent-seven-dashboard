"""The operated pipeline: trading sessions, restatement detection, the data contract, the run ledger."""

import json
import sys
import tempfile
import unittest
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from m7 import checks, data, incident, ledger, pipeline, sessions, watchdog  # noqa: E402

CACHE_PRICES, CACHE_RATES = data.load_cache()
LAST = pd.Timestamp("2026-11-16")
AFTER_CLOSE = "2026-11-16T22:17:00Z"  # the scheduled run's time on a normal weekday


def history(end=LAST):
    return CACHE_PRICES.loc[:end, data.SERIES].copy(), CACHE_RATES.loc[:end].copy()


class Sessions(unittest.TestCase):
    def test_expected_session_waits_for_the_close_to_settle(self):
        self.assertEqual(sessions.expected_last_session("2026-11-16T21:00Z"), pd.Timestamp("2026-11-13"))  # 4pm ET
        self.assertEqual(sessions.expected_last_session("2026-11-16T21:31Z"), LAST)

    def test_weekends_holidays_and_early_closes(self):
        self.assertEqual(sessions.expected_last_session("2026-11-21T12:00Z"), pd.Timestamp("2026-11-20"))
        self.assertEqual(sessions.expected_last_session("2026-11-26T23:00Z"), pd.Timestamp("2026-11-25"))  # Thanksgiving
        self.assertEqual(sessions.expected_last_session("2026-11-27T18:31Z"), pd.Timestamp("2026-11-27"))  # 1pm close

    def test_sessions_behind(self):
        self.assertEqual(sessions.sessions_behind("2026-11-13", "2026-11-17T23:00Z"), 2)
        self.assertEqual(sessions.sessions_behind("2026-11-25", "2026-11-26T23:00Z"), 0)


class Restatements(unittest.TestCase):
    def setUp(self):
        self.published, _ = history("2026-11-13")
        self.fetched, _ = history()

    def test_unchanged_history_has_no_events(self):
        self.assertEqual(checks.restatements(self.published, self.fetched), ([], []))

    def test_dividend_rescales_earlier_prices_and_is_accepted(self):
        ex_date = pd.Timestamp("2026-08-11")
        self.fetched.loc[self.fetched.index < ex_date, "AAPL"] *= 0.9976
        events, problems = checks.restatements(self.published, self.fetched)
        self.assertEqual(problems, [])
        self.assertEqual(events, [{"ticker": "AAPL", "kind": "dividend", "effective": "2026-08-11", "factor": 0.9976}])

    def test_split_and_dividend_together(self):
        self.fetched.loc[self.fetched.index < "2024-06-10", "NVDA"] *= 0.1
        self.fetched.loc[self.fetched.index < "2025-03-12", "NVDA"] *= 0.9999
        events, problems = checks.restatements(self.published, self.fetched)
        self.assertEqual(problems, [])
        self.assertEqual([(e["kind"], e["effective"]) for e in events], [("split", "2024-06-10"), ("dividend", "2025-03-12")])

    def test_ex_dividend_on_a_new_day_left_out_as_incomplete(self):
        # Production, Nov 20 2026: MSFT went ex-dividend on the newest day, but that day was left out
        # because another series had no price yet. The rescaling still has to be recognized.
        raw = self.fetched.copy()
        raw.loc[raw.index < LAST, "MSFT"] *= 0.9981
        raw.loc[LAST, "META"] = float("nan")
        events, problems = checks.restatements(self.published, raw.dropna(), raw)
        self.assertEqual(problems, [])
        self.assertEqual(events, [{"ticker": "MSFT", "kind": "dividend", "effective": "2026-11-16", "factor": 0.9981}])

    def test_rescaling_with_no_newer_day_at_all_is_still_a_problem(self):
        raw = self.published.copy()
        raw["MSFT"] *= 0.9981
        events, problems = checks.restatements(self.published, raw, raw)
        self.assertEqual(events, [])
        self.assertIn("MSFT", problems[0])

    def test_ex_dividend_on_the_new_day_rescales_all_published_history(self):
        self.fetched.loc[self.fetched.index < LAST, "MSFT"] *= 0.9981
        events, problems = checks.restatements(self.published, self.fetched)
        self.assertEqual(problems, [])
        self.assertEqual(events[0]["effective"], "2026-11-16")

    def test_small_revision_of_the_latest_close_is_a_correction(self):
        self.fetched.loc["2026-11-13", "TSLA"] *= 1.002
        events, problems = checks.restatements(self.published, self.fetched)
        self.assertEqual((problems, events[0]["kind"]), ([], "correction"))

    def test_rounding_noise_seen_in_production_is_not_a_revision(self):
        self.fetched.loc["2026-11-13", "SPY"] *= 1 - 1.352744e-05  # SPY 739.96 -> 739.95, observed Nov 18, 2026
        self.fetched.loc["2026-06-05", "META"] *= 1 + 1.03e-07
        self.assertEqual(checks.restatements(self.published, self.fetched), ([], []))
        self.assertAlmostEqual(checks.rounding_noise(self.published, self.fetched), 1.352744e-05, places=9)

    def test_irregular_changes_to_history_are_problems(self):
        self.fetched.loc["2025-01-15", "META"] *= 1.03  # one past day edited, nothing before or after
        events, problems = checks.restatements(self.published, self.fetched)
        self.assertEqual(len(problems), 1)
        self.assertIn("META", problems[0])

    def test_lost_history_is_a_problem(self):
        _, problems = checks.restatements(self.published, self.fetched.drop(pd.Timestamp("2026-06-01")))
        self.assertIn("missing from the new download", problems[0])


class Contract(unittest.TestCase):
    def statuses(self, prices, now=AFTER_CLOSE, rates=CACHE_RATES):
        return {c.name: c.status for c in checks.contract(prices, rates, now)}

    def test_cached_history_passes(self):
        status = self.statuses(history()[0])
        self.assertEqual({k: v for k, v in status.items() if k != "moves"},
                         {"schema": "pass", "complete": "pass", "ordered": "pass", "calendar": "pass",
                          "freshness": "pass", "risk_free": "pass"})
        self.assertEqual(status["moves"], "warn")  # META fell 26% on Feb 3, 2022: real, so a warning only

    def test_a_missing_session_fails(self):
        self.assertEqual(self.statuses(history()[0].drop(pd.Timestamp("2026-07-02")))["calendar"], "fail")

    def test_an_implausible_move_fails(self):
        prices = history()[0]
        prices.loc[LAST, "AAPL"] *= 3
        self.assertEqual(self.statuses(prices)["moves"], "fail")

    def test_staleness_warns_then_fails_without_blocking(self):
        prices = history()[0]
        self.assertEqual(self.statuses(prices, now="2026-11-17T23:00Z")["freshness"], "warn")
        stale = [c for c in checks.contract(prices, CACHE_RATES, "2026-11-19T23:00Z") if c.name == "freshness"][0]
        self.assertEqual((stale.status, stale.blocks), ("fail", False))


class PipelineRuns(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.state, self.site = self.tmp / "state", self.tmp / "site"
        ledger.State(self.state).save(*history("2026-11-12"))

    def fetch(self, prices, rates=None, error=None):
        def fetcher():
            if error:
                raise error
            return prices, rates if rates is not None else CACHE_RATES
        return fetcher

    def runs(self):
        return ledger.State(self.state).read(ledger.State(self.state).runs)

    def test_new_days_publish_and_are_recorded(self):
        record = pipeline.run(self.state, self.site, self.fetch(history()[0]), now=AFTER_CLOSE)
        self.assertEqual((record["status"], record["rows_added"], record["as_of"]), ("published", 2, "2026-11-16"))
        page = json.loads((self.site / "data.json").read_text())
        self.assertEqual(page["dates"][-1], "2026-11-16")
        status = json.loads((self.site / "status.json").read_text())
        self.assertEqual(status["latest"]["run_id"], record["run_id"])
        self.assertEqual(len(self.runs()), 1)

    def test_an_incomplete_latest_day_is_left_out_and_explained(self):
        prices = history()[0]
        prices.loc[LAST, "NVDA"] = float("nan")
        record = pipeline.run(self.state, self.site, self.fetch(prices), now=AFTER_CLOSE)
        self.assertEqual((record["status"], record["as_of"]), ("published", "2026-11-13"))
        download = next(c for c in record["checks"] if c["name"] == "download")
        self.assertEqual((download["status"], download["detail"]),
                         ("warn", "left out incomplete day(s): 2026-11-16 (no price for NVDA)"))

    def test_a_failed_download_keeps_the_last_good_data(self):
        record = pipeline.run(self.state, self.site, self.fetch(None, error=ConnectionError("Yahoo down")), now=AFTER_CLOSE)
        self.assertEqual(record["status"], "failed")
        self.assertIn("Yahoo down", record["error"])
        self.assertEqual(json.loads((self.site / "data.json").read_text())["dates"][-1], "2026-11-12")
        self.assertEqual(ledger.State(self.state).load()[0].index[-1], pd.Timestamp("2026-11-12"))

    def test_an_unexplained_revision_blocks_publishing(self):
        prices = history()[0]
        prices.loc["2025-05-05", "GOOGL"] *= 1.05
        record = pipeline.run(self.state, self.site, self.fetch(prices), now=AFTER_CLOSE)
        self.assertEqual(record["status"], "failed")
        self.assertIn("restatements", record["error"])
        self.assertEqual(ledger.State(self.state).load()[0].index[-1], pd.Timestamp("2026-11-12"))

    def test_an_operator_can_accept_a_revision_with_a_logged_reason(self):
        prices = history()[0]
        prices.loc["2025-05-05", "GOOGL"] *= 1.05
        record = pipeline.run(self.state, self.site, self.fetch(prices), now=AFTER_CLOSE,
                              accept_revisions="Yahoo corrected a bad print, checked against Nasdaq")
        self.assertEqual(record["status"], "published")
        event = ledger.State(self.state).read(ledger.State(self.state).events)[0]
        self.assertEqual((event["kind"], event["reason"]), ("accepted_by_operator", "Yahoo corrected a bad print, checked against Nasdaq"))
        self.assertIn("GOOGL", event["changes"][0])

    def test_a_dividend_publishes_and_is_logged(self):
        prices = history()[0]
        prices.loc[prices.index < "2026-11-14", "SPY"] *= 0.9965
        record = pipeline.run(self.state, self.site, self.fetch(prices), now=AFTER_CLOSE)
        self.assertEqual(record["status"], "published")
        state = ledger.State(self.state)
        self.assertEqual(state.read(state.events)[0]["ticker"], "SPY")
        self.assertAlmostEqual(state.load()[0].loc["2026-11-12", "SPY"], prices.loc["2026-11-12", "SPY"])

    def test_a_dividend_on_an_incomplete_new_day_does_not_block_publishing(self):
        prices = history("2026-11-13")[0]
        prices.loc[prices.index < "2026-11-13", "MSFT"] *= 0.9981
        prices.loc["2026-11-13", "META"] = float("nan")
        record = pipeline.run(self.state, self.site, self.fetch(prices), now="2026-11-13T22:17:00Z")
        self.assertIn(record["status"], ("published", "degraded"))
        self.assertIsNone(record["error"])
        state = ledger.State(self.state)
        event = state.read(state.events)[0]
        self.assertEqual((event["ticker"], event["effective"]), ("MSFT", "2026-11-13"))
        self.assertAlmostEqual(state.load()[0].loc["2026-11-12", "MSFT"], prices.loc["2026-11-12", "MSFT"])

    def test_stale_source_still_publishes_but_is_degraded(self):
        record = pipeline.run(self.state, self.site, self.fetch(history("2026-11-12")[0]), now="2026-11-18T23:00Z")
        self.assertEqual(record["status"], "degraded")
        self.assertIsNone(record["error"])

    def test_first_run_bootstraps_from_the_repository_cache(self):
        empty = self.tmp / "fresh"
        record = pipeline.run(empty, self.site, self.fetch(history()[0]), now=AFTER_CLOSE)
        self.assertIn("bootstrapped_from", record)
        self.assertEqual(record["status"], "published")


class Timeliness(unittest.TestCase):
    def run_record(self, finished, as_of, status="published"):
        return {"run_id": finished, "finished": finished, "as_of": as_of, "status": status}

    def test_on_time_late_missed_and_slo(self):
        runs = [self.run_record("2026-11-09T22:30:00Z", "2026-11-09"),
                self.run_record("2026-11-10T22:30:00Z", "2026-11-10"),
                self.run_record("2026-11-12T03:00:00Z", "2026-11-11"),        # after midnight UTC: late
                self.run_record("2026-11-12T22:30:00Z", "2026-11-11", "failed"),  # failed: Nov 12 never published
                self.run_record("2026-11-13T22:30:00Z", "2026-11-13")]
        days = {d["session"]: d["state"] for d in ledger.timeliness(runs, now="2026-11-14T12:00Z")}
        # Nov 12's own run failed, so its prices first went live with Nov 13's run: after Nov 12's deadline.
        self.assertEqual(days, {"2026-11-09": "on_time", "2026-11-10": "on_time", "2026-11-11": "late",
                                "2026-11-12": "late", "2026-11-13": "on_time"})
        runs[-1]["finished"] = "2026-11-14T01:00:00Z"  # now Nov 13's run itself finishes after midnight UTC
        days = {d["session"]: d["state"] for d in ledger.timeliness(runs, now="2026-11-14T12:00Z")}
        self.assertEqual((days["2026-11-12"], days["2026-11-13"]), ("late", "late"))
        slo = ledger.status_payload(runs, [], now="2026-11-14T12:00Z")["slo"]
        self.assertEqual((slo["on_time"], slo["scored"], slo["rate"]), (2, 5, 0.4))


class Incidents(unittest.TestCase):
    URL = "https://github.com/x/y/actions/runs/1"

    def record(self, status, error=None):
        return {"run_id": "abc", "trigger": "schedule", "status": status, "as_of": "2026-11-13", "rows_added": 1,
                "started": "2026-11-16T22:17:00Z", "finished": "2026-11-16T22:19:00Z", "error": error, "checks": []}

    def test_failure_opens_an_incident(self):
        action, payload = incident.decide(self.record("failed", "ConnectionError: down"), None, self.URL)
        self.assertEqual(action, "open")
        self.assertIn("2026-11-16", payload["title"])
        self.assertIn("ConnectionError: down", payload["body"])

    def test_repeat_failure_comments_on_the_open_incident(self):
        action, payload = incident.decide(self.record("failed", "x"), {"number": 7, "createdAt": "2026-11-15T22:19:00Z"}, self.URL)
        self.assertEqual((action, payload["number"]), ("comment", 7))

    def test_recovery_closes_with_the_duration(self):
        action, payload = incident.decide(self.record("published"), {"number": 7, "createdAt": "2026-11-15T22:19:00Z"}, self.URL)
        self.assertEqual(action, "close")
        self.assertIn("24.0 hours", payload["body"])

    def test_healthy_run_without_incident_does_nothing(self):
        self.assertEqual(incident.decide(self.record("published"), None, self.URL), ("none", {}))

    def test_a_crash_without_a_record_opens_an_incident(self):
        self.assertEqual(incident.decide(None, None, self.URL)[0], "open")


class Watchdog(unittest.TestCase):
    def run_record(self, as_of, status="published", finished="2026-11-16T22:19:00Z"):
        return {"run_id": as_of, "status": status, "as_of": as_of, "finished": finished}

    def test_quiet_after_an_on_time_run(self):
        self.assertIsNone(watchdog.check([self.run_record("2026-11-16")], now="2026-11-17T13:41Z"))

    def test_one_late_day_is_not_yet_an_alert(self):
        self.assertIsNone(watchdog.check([self.run_record("2026-11-16")], now="2026-11-18T13:41Z"))

    def test_two_missing_trading_days_alert_even_without_any_failed_run(self):
        problem = watchdog.check([self.run_record("2026-11-16")], now="2026-11-19T13:41Z")
        self.assertIn("2 trading days behind", problem)

    def test_weekends_and_holidays_are_not_missing_days(self):
        self.assertIsNone(watchdog.check([self.run_record("2026-11-25")], now="2026-11-30T13:41Z"))  # Thanksgiving + weekend + early close

    def test_failed_runs_do_not_count_as_publishing(self):
        runs = [self.run_record("2026-11-12"), self.run_record("2026-11-12", "failed", "2026-11-18T22:19:00Z")]
        self.assertIn("(failed)", watchdog.check(runs, now="2026-11-19T13:41Z"))

    def test_an_empty_ledger_alerts(self):
        self.assertIsNotNone(watchdog.check([], now="2026-11-19T13:41Z"))


class Badges(unittest.TestCase):
    def test_badges_follow_the_target_and_freshness(self):
        runs = [{"run_id": "a", "finished": "2026-11-16T22:30:00Z", "as_of": "2026-11-16", "status": "published"}]
        status = ledger.status_payload(runs, [], now="2026-11-17T12:00Z")
        made = ledger.badges(status, now="2026-11-17T12:00Z")
        self.assertEqual(made["badge-on-time.json"], {"schemaVersion": 1, "label": "on time",
                                                      "message": "100% of last 1 days", "color": "brightgreen"})
        self.assertEqual(made["badge-data.json"]["color"], "brightgreen")
        self.assertEqual(ledger.badges(status, now="2026-11-20T12:00Z")["badge-data.json"]["color"], "red")


if __name__ == "__main__":
    unittest.main()
