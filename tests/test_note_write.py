"""The writer, tested with a stand-in API client (no network, no key), and the saved example."""

import json
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from m7.config import PRICES_CSV  # noqa: E402
from m7.note import write  # noqa: E402
from m7.note.example import example_payload, load_example  # noqa: E402
from m7.note.facts import build_facts  # noqa: E402
from m7.note.guard import check  # noqa: E402

PRICES = pd.read_csv(PRICES_CSV, index_col="Date", parse_dates=True)
SAVED = load_example()
FACTS = build_facts(PRICES, SAVED["as_of"])


class StandIn:
    """Records the request and returns a canned response shaped like the SDK's."""

    def __init__(self, text=None, stop_reason="end_turn"):
        self.text = json.dumps(SAVED["note"]) if text is None else text
        self.stop_reason = stop_reason
        self.request = None
        self.messages = self

    def create(self, **request):
        self.request = request
        return SimpleNamespace(
            model=request["model"], stop_reason=self.stop_reason, _request_id="req_test",
            usage=SimpleNamespace(input_tokens=1500, output_tokens=300),
            content=[SimpleNamespace(type="text", text=self.text)],
        )


class Request(unittest.TestCase):
    def setUp(self):
        self.client = StandIn()
        write.write_note(FACTS, self.client)
        self.req = self.client.request

    def test_model_effort_and_schema(self):
        self.assertEqual(self.req["model"], "claude-opus-5-5")
        self.assertEqual(self.req["output_config"]["effort"], "medium")
        self.assertEqual(self.req["output_config"]["format"]["type"], "json_schema")
        self.assertEqual(self.req["output_config"]["format"]["schema"]["required"],
                         ["headline", "headline_claims", "bullets"])

    def test_the_model_sees_only_the_fact_sheet(self):
        sent = json.loads(self.req["messages"][0]["content"].split("\n", 1)[1])
        self.assertEqual(set(sent), {"date", "facts", "true_claims"})
        self.assertEqual(sent["facts"]["NVDA.move_1d"], "Nvidia fell 4.1%")
        self.assertEqual(sent["true_claims"]["laggard"], ["GOOGL", "NVDA"])
        self.assertTrue(sent["true_claims"]["all_down"])

    def test_claim_types_match_the_guard(self):
        from m7.note.guard import CLAIM_TYPES
        self.assertEqual(set(write.CLAIM_TYPES), CLAIM_TYPES)


class Response(unittest.TestCase):
    def test_a_normal_answer_is_parsed_with_its_metadata(self):
        note, meta = write.write_note(FACTS, StandIn())
        self.assertEqual(note, SAVED["note"])
        self.assertEqual((meta["request_id"], meta["input_tokens"], meta["output_tokens"]), ("req_test", 1500, 300))
        self.assertEqual(meta["prompt_version"], write.PROMPT_VERSION)

    def test_a_refusal_is_a_failed_note(self):
        with self.assertRaises(write.NoteFailed) as caught:
            write.write_note(FACTS, StandIn(stop_reason="refusal"))
        self.assertEqual(caught.exception.meta["stop_reason"], "refusal")

    def test_a_cut_off_answer_is_a_failed_note(self):
        with self.assertRaises(write.NoteFailed):
            write.write_note(FACTS, StandIn(stop_reason="max_tokens"))

    def test_an_answer_that_is_not_json_is_a_failed_note(self):
        with self.assertRaises(write.NoteFailed):
            write.write_note(FACTS, StandIn(text="Here is your note: ..."))


class SavedExample(unittest.TestCase):
    def test_the_example_passes_the_guard(self):
        self.assertEqual(check(SAVED["note"], FACTS), [])

    def test_the_example_renders_as_expected(self):
        p = example_payload(PRICES)
        self.assertTrue(p["example"])
        self.assertEqual(p["as_of"], "2026-11-16")
        self.assertEqual(p["headline"], "The seven stocks fell 2.7% on average, and Apple was the strongest")
        self.assertEqual(p["bullets"], [
            "Alphabet fell 4.1% and Nvidia fell 4.1%, tying for the weakest result.",
            "Apple fell 1.0%, the strongest in the group, and remains up 30.2% so far in 2026.",
            "Across the group, all seven fell, leaving it 0.8 percentage points behind the S&P 500 fund (SPY).",
        ])


if __name__ == "__main__":
    unittest.main()
