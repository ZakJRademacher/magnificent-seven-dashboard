"""The daily note inside the pipeline, with a stand-in model (no network, no key, no cost).

What must hold:
- only live runs call the model, and only once per day's facts;
- a note the guard rejects, or any API error, is a warning: prices still publish and the
  previous note stays up;
- a saved note is re-checked against the current data before it is shown again;
- dry runs show the example note and never touch the saved one.
"""

import json
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from m7 import data, ledger, pipeline  # noqa: E402
from m7.note import publish  # noqa: E402

CACHE_PRICES, CACHE_RATES = data.load_cache()
AFTER_CLOSE = "2026-11-16T22:17:00Z"


def history(end="2026-11-16"):
    return CACHE_PRICES.loc[:end, data.SERIES].copy()


class Writer:
    """Answers like the API with an honest note built from the request's true claims."""

    def __init__(self, bad=False, error=None):
        self.bad, self.error, self.calls = bad, error, 0
        self.messages = self

    def create(self, **request):
        self.calls += 1
        if self.error:
            raise self.error
        claims = json.loads(request["messages"][0]["content"].split("\n", 1)[1])["true_claims"]

        def names(ids):
            return " and ".join("{" + t + ".move_1d}" for t in ids)

        note = {"headline": "{group.move_1d}", "headline_claims": [], "bullets": [
            {"text": names(claims["leader"]) + ", the best result in the group.",
             "claims": [{"type": "leader", "ids": claims["leader"]}]},
            {"text": names(claims["laggard"]) + ", the weakest result in the group.",
             "claims": [{"type": "laggard", "ids": claims["laggard"]}]},
            {"text": "Overall, {count.up}, and {count.down}.", "claims": []},
        ]}
        if self.bad:
            note["bullets"][2]["text"] = "Overall, {count.up}; investors should buy."
        return SimpleNamespace(model=request["model"], stop_reason="end_turn", _request_id="req_test",
                               usage=SimpleNamespace(input_tokens=2600, output_tokens=900),
                               content=[SimpleNamespace(type="text", text=json.dumps(note))])


class NoCalls:
    """Fails the test if anything tries to call the model."""

    @property
    def messages(self):
        raise AssertionError("the model must not be called on this run")


class NoteInThePipeline(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.state, self.site = self.tmp / "state", self.tmp / "site"
        ledger.State(self.state).save(history("2026-11-12"), CACHE_RATES.loc[:"2026-11-12"])

    def run_once(self, prices=None, mode="live", client=None, now=AFTER_CLOSE, error=None):
        def fetch():
            if error:
                raise error
            return (history() if prices is None else prices), CACHE_RATES
        return pipeline.run(self.state, self.site, fetch, now=now, note=mode, client=client)

    def site_note(self):
        path = self.site / "note.json"
        return json.loads(path.read_text(encoding="utf-8")) if path.exists() else None

    def note_check(self, record):
        return next((c for c in record["checks"] if c["name"] == "note"), None)

    def test_a_live_run_writes_checks_saves_and_publishes_the_note(self):
        writer = Writer()
        record = self.run_once(client=writer)
        self.assertEqual(writer.calls, 1)
        self.assertEqual(record["status"], "published")
        self.assertEqual(self.note_check(record)["status"], "pass")
        self.assertEqual(record["note"]["status"], "written")
        self.assertEqual(record["note"]["input_tokens"], 2600)
        shown = self.site_note()
        self.assertEqual((shown["as_of"], shown["example"]), ("2026-11-16", False))
        self.assertNotIn("{", shown["headline"] + "".join(shown["bullets"]))
        saved = json.loads((self.state / "note.json").read_text(encoding="utf-8"))
        self.assertEqual((saved["as_of"], saved["facts_hash"]), ("2026-11-16", shown["facts_hash"]))

    def test_a_rerun_for_the_same_facts_does_not_call_the_model_again(self):
        writer = Writer()
        self.run_once(client=writer)
        record = self.run_once(client=writer)
        self.assertEqual(writer.calls, 1)
        self.assertIn("already written", self.note_check(record)["detail"])
        self.assertEqual(self.site_note()["as_of"], "2026-11-16")

    def test_rounding_noise_in_a_new_download_does_not_rewrite_the_note(self):
        writer = Writer()
        self.run_once(client=writer)
        noisy = history()
        noisy.loc["2026-11-16", "AAPL"] *= 1 + 1e-6
        self.run_once(noisy, client=writer)
        self.assertEqual(writer.calls, 1)

    def test_a_corrected_close_for_the_day_gets_a_new_note(self):
        writer = Writer()
        self.run_once(client=writer)
        corrected = history()
        corrected.loc["2026-11-16", "AAPL"] *= 1.005  # a late correction the price checks accept
        record = self.run_once(corrected, client=writer)
        self.assertEqual(record["status"], "published")
        self.assertEqual(writer.calls, 2)

    def test_a_rejected_note_is_not_published_and_the_previous_one_stays(self):
        self.run_once(history("2026-11-13"), client=Writer(), now="2026-11-13T22:17:00Z")
        record = self.run_once(client=Writer(bad=True))
        self.assertEqual(record["status"], "published")
        check = self.note_check(record)
        self.assertEqual((check["status"], check["blocks"]), ("warn", False))
        self.assertIn("investors", check["detail"])
        self.assertEqual(record["note"]["status"], "rejected")
        self.assertEqual(self.site_note()["as_of"], "2026-11-13")

    def test_an_api_error_never_stops_the_prices(self):
        record = self.run_once(client=Writer(error=ConnectionError("API unreachable")))
        self.assertEqual(record["status"], "published")
        self.assertEqual(json.loads((self.site / "data.json").read_text())["dates"][-1], "2026-11-16")
        check = self.note_check(record)
        self.assertEqual(check["status"], "warn")
        self.assertIn("API unreachable", check["detail"])
        self.assertIsNone(self.site_note())

    def test_no_note_is_written_when_the_prices_did_not_publish(self):
        record = self.run_once(client=NoCalls(), error=ConnectionError("Yahoo down"))
        self.assertEqual(record["status"], "failed")
        self.assertIn("price data", self.note_check(record)["detail"])

    def test_runs_that_dont_write_notes_never_call_the_model(self):
        self.run_once(client=Writer())
        record = self.run_once(mode="saved", client=NoCalls())
        self.assertEqual(self.note_check(record)["status"], "pass")
        self.assertEqual(self.site_note()["as_of"], "2026-11-16")

    def test_a_saved_run_with_nothing_saved_shows_no_note(self):
        record = self.run_once(mode="saved", client=NoCalls())
        self.assertIsNone(self.note_check(record))
        self.assertIsNone(self.site_note())

    def test_a_dry_run_shows_the_example_and_saves_nothing(self):
        record = self.run_once(mode="example", client=NoCalls())
        self.assertEqual(self.note_check(record)["status"], "pass")
        self.assertTrue(self.site_note()["example"])
        self.assertFalse((self.state / "note.json").exists())

    def test_off_means_no_note_at_all(self):
        (self.site).mkdir(parents=True, exist_ok=True)
        record = self.run_once(mode="off", client=NoCalls())
        self.assertIsNone(self.note_check(record))
        self.assertIsNone(self.site_note())


class Recheck(unittest.TestCase):
    def test_a_saved_note_whose_claims_no_longer_hold_is_not_shown(self):
        tmp = Path(tempfile.mkdtemp())
        prices = history()
        publish.note_step(tmp, prices, "live", "2026-11-16T22:20:00Z", client=Writer())
        saved = publish.load_saved(tmp)
        self.assertIsNotNone(publish.publishable(saved, prices))
        changed = prices.copy()
        changed.loc["2026-11-16", "TSLA"] *= 1.5  # Tesla would now lead, so the saved "best" claim is false
        self.assertIsNone(publish.publishable(saved, changed))


if __name__ == "__main__":
    unittest.main()
