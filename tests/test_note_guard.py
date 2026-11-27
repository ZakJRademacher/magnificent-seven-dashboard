"""The renderer and the guard, tested with a good note and deliberately bad ones.

Most tests swap in a minimal digit-and-symbol check for find_banned_numbers so the
rest of the guard can be tested on its own. GuardWithRealNumberCheck uses the
real one.
"""

import copy
import re
import sys
import unittest
from pathlib import Path
from unittest import mock

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from m7.config import BENCHMARK, TICKERS  # noqa: E402
from m7.note import guard  # noqa: E402
from m7.note.facts import build_facts  # noqa: E402
from m7.note.render import UnknownFact, render, strip_placeholders  # noqa: E402

DATES = pd.bdate_range("2024-12-24", periods=8)
FLAT6 = [100.0] * 6


def _prices():
    data = {t: [100.0] * len(DATES) for t in TICKERS + [BENCHMARK]}
    data.update({"AAPL": FLAT6 + [110.0, 121.0], "MSFT": FLAT6 + [100.0, 95.0], BENCHMARK: FLAT6 + [100.0, 100.5]})
    return pd.DataFrame(data, index=DATES)


# Jan 2: Apple +10.0% (best, biggest), Microsoft -5.0% (worst), five flat, group +0.7%, 0.2 points ahead of SPY.
FACTS = build_facts(_prices(), "2025-01-02")

GOOD = {
    "headline": "Apple led a quiet session",
    "headline_claims": [{"type": "leader", "ids": ["AAPL"]}],
    "bullets": [
        {"text": "{AAPL.move_1d}, the best result in the group.", "claims": [{"type": "leader", "ids": ["AAPL"]}]},
        {"text": "{MSFT.move_1d}, while {GOOGL.move_1d}.", "claims": []},
        {"text": "Overall, {group.move_1d}, {group.gap_to_spy_1d}.", "claims": []},
    ],
}


def stand_in_numbers(text):
    return re.findall(r"\d+|%|\$", text)


def with_bullet(text, claims=()):
    note = copy.deepcopy(GOOD)
    note["bullets"][0] = {"text": text, "claims": list(claims)}
    return note


class Renderer(unittest.TestCase):
    def test_placeholders_become_fact_text(self):
        shown = render(GOOD, FACTS)
        self.assertEqual(shown["bullets"][0], "Apple rose 10.0%, the best result in the group.")
        self.assertEqual(shown["bullets"][2], "Overall, the seven stocks rose 0.7% on average, "
                                              "0.2 percentage points ahead of the S&P 500 fund (SPY).")
        self.assertEqual(shown["as_of"], "2025-01-02")

    def test_a_sentence_starting_with_a_placeholder_is_capitalised(self):
        note = copy.deepcopy(GOOD)
        note["bullets"][2]["text"] = "{group.move_1d}."
        self.assertEqual(render(note, FACTS)["bullets"][2], "The seven stocks rose 0.7% on average.")

    def test_unknown_placeholder(self):
        with self.assertRaises(UnknownFact):
            render(with_bullet("{AAPL.move_2d}"), FACTS)

    def test_strip_leaves_only_the_writers_words(self):
        self.assertEqual(strip_placeholders("{AAPL.move_1d}, the best").strip(), ", the best")


@mock.patch.object(guard, "find_banned_numbers", stand_in_numbers)
class Guard(unittest.TestCase):
    def assertRejected(self, note, fragment):
        problems = guard.check(note, FACTS)
        self.assertTrue(any(fragment in p for p in problems), f"expected {fragment!r} in {problems}")

    def test_the_good_note_passes(self):
        self.assertEqual(guard.check(GOOD, FACTS), [])

    def test_typed_number(self):
        self.assertRejected(with_bullet("{AAPL.move_1d}, its best day in 3 weeks.",
                                        [{"type": "leader", "ids": ["AAPL"]}]), "numbers must come from placeholders")

    def test_unknown_placeholder(self):
        self.assertRejected(with_bullet("{AAPL.move_2d}."), "unknown placeholder")

    def test_wrong_leader(self):
        self.assertRejected(with_bullet("{MSFT.move_1d}, the best in the group.",
                                        [{"type": "leader", "ids": ["MSFT"]}]), "is false")

    def test_superlative_without_a_tag(self):
        self.assertRejected(with_bullet("{AAPL.move_1d}, the best in the group."), "needs a tagged leader claim")

    def test_false_all_claim(self):
        self.assertRejected(with_bullet("Not all followed: {AAPL.move_1d}.", [{"type": "all_up"}]), "is false")

    def test_direction_word_outside_a_placeholder(self):
        self.assertRejected(with_bullet("Microsoft slipped: {MSFT.change_1d}."), "direction words")

    def test_a_direction_word_backed_by_a_true_claim_is_fine(self):
        # Found in a live eval: "the only stock in the group to fall", tagged only_down. Jan 2: only MSFT fell.
        ok = with_bullet("{MSFT.move_1d}, the only stock in the group to fall.", [{"type": "only_down", "ids": ["MSFT"]}])
        problems = guard.check(ok, FACTS)
        self.assertFalse(any("direction words" in p for p in problems), problems)
        self.assertFalse(any("is false" in p for p in problems), problems)

    def test_the_backing_claim_must_point_the_same_way(self):
        # A down-direction claim doesn't excuse an up word.
        self.assertRejected(with_bullet("{MSFT.move_1d}, the only one; the rest rose.",
                                        [{"type": "only_down", "ids": ["MSFT"]}]), "direction words")

    def test_the_backing_claim_must_be_true(self):
        self.assertRejected(with_bullet("{AAPL.move_1d}, the only stock to fall.",
                                        [{"type": "only_down", "ids": ["AAPL"]}]), "is false")

    def test_flat_is_never_backed(self):
        self.assertRejected(with_bullet("{MSFT.move_1d}, the only one; most were flat.",
                                        [{"type": "only_down", "ids": ["MSFT"]}]), "direction words")

    def test_advice(self):
        self.assertRejected(with_bullet("{AAPL.move_1d}; investors should watch it."), "advice")

    def test_prediction(self):
        self.assertRejected(with_bullet("{AAPL.move_1d} and will likely keep going."), "advice")

    def test_unknown_company_and_ticker(self):
        self.assertRejected(with_bullet("{AAPL.move_1d}, unlike Netflix."), "unknown names")
        self.assertRejected(with_bullet("{AAPL.move_1d}, unlike NFLX."), "unknown names")

    def test_a_figure_without_its_company_name_is_rejected(self):
        # Found by the judge in a live eval: "Apple fell 2.6% and fell 0.7%" (the 0.7% was Microsoft's).
        self.assertRejected(with_bullet("{AAPL.move_1d} and {MSFT.change_1d}."), "must follow the same company's name")

    def test_a_figure_after_its_company_name_is_fine(self):
        for text in ["{AAPL.move_1d}, leaving it {AAPL.change_ytd}.", "Apple, meanwhile, {AAPL.change_1d}.",
                     "Over the week, AAPL is {AAPL.change_5d}."]:
            with self.subTest(text=text):
                problems = guard.check(with_bullet(text), FACTS)
                self.assertFalse(any("same company" in p for p in problems), problems)

    def test_the_name_must_be_in_the_same_sentence(self):
        self.assertRejected(with_bullet("{AAPL.move_1d}. It is {AAPL.change_ytd}."), "must follow the same company's name")

    def test_known_names_are_fine(self):
        self.assertEqual(guard.check(with_bullet("Among the Magnificent Seven, {AAPL.move_1d}."), FACTS), [])

    def test_bullet_without_figures(self):
        self.assertRejected(with_bullet("A quiet day for most names."), "has no figures")

    def test_unknown_claim_type(self):
        self.assertRejected(with_bullet("{AAPL.move_1d}.", [{"type": "made_up"}]), "unknown claim type")

    def test_too_long(self):
        self.assertRejected(with_bullet("{AAPL.move_1d}" + ", and then some more words" * 10 + "."), "characters")

    def test_headline_superlative_needs_a_tag(self):
        note = copy.deepcopy(GOOD)
        note["headline_claims"] = []
        self.assertRejected(note, "headline: ['led'] needs a tagged leader claim")

    def test_wrong_number_of_bullets(self):
        note = copy.deepcopy(GOOD)
        note["bullets"].pop()
        self.assertEqual(guard.check(note, FACTS), ["note: needs exactly 3 bullets"])

    # Found in the Codex review of the branch.
    def test_a_claim_must_be_about_a_stock_the_sentence_names(self):
        self.assertRejected(with_bullet("{MSFT.move_1d}, the best result in the group.",
                                        [{"type": "leader", "ids": ["AAPL"]}]), "names a stock the text doesn't")

    def test_a_figure_follows_the_company_named_just_before_it(self):
        self.assertRejected(with_bullet("{AAPL.move_1d}, while {MSFT.move_1d} and remained {AAPL.change_ytd}."),
                            "must follow the same company's name")

    def test_a_closing_price_needs_its_company_too(self):
        self.assertRejected(with_bullet("{AAPL.move_1d}. Microsoft closed at {AAPL.close}."),
                            "must follow the same company's name")
        problems = guard.check(with_bullet("{AAPL.move_1d}, closing at {AAPL.close}."), FACTS)
        self.assertFalse(any("same company" in p for p in problems), problems)

    def test_advice_without_the_usual_words(self):
        for text in ["{AAPL.move_1d}. Consider adding it to your portfolio.",
                     "{AAPL.move_1d} after it missed earnings estimates.",
                     "{AAPL.move_1d}, and analysts reported the news."]:
            with self.subTest(text=text):
                self.assertRejected(with_bullet(text), "advice")

    def test_an_unknown_company_starting_a_sentence(self):
        self.assertRejected(with_bullet("Broadcom announced results. {AAPL.move_1d}."), "unknown names")

    def test_ordinary_sentence_starters_are_fine(self):
        for text in ["Overall, {group.move_1d}.", "Elsewhere, {MSFT.move_1d}.", "Meanwhile, {MSFT.move_1d}.",
                     "Apple, meanwhile, {AAPL.change_1d}."]:
            with self.subTest(text=text):
                problems = guard.check(with_bullet(text), FACTS)
                self.assertFalse(any("unknown names" in p for p in problems), problems)

    def test_an_empty_only_claim_is_false(self):
        # On a day when all seven fall, an only_up tag with no stocks must not unlock "only" and "rose".
        prices = _prices()
        prices.loc[DATES[-1]] = prices.loc[DATES[-2]] * 0.9
        facts = build_facts(prices, "2025-01-02")
        problems = guard.check(with_bullet("Only Apple rose; {count.down}.", [{"type": "only_up", "ids": []}]), facts)
        self.assertTrue(any(p.startswith("bullet 1: claim") and "is false" in p for p in problems), problems)

    def test_malformed_claims_are_rejected_not_raised(self):
        note = copy.deepcopy(GOOD)
        note["headline_claims"] = [None]
        self.assertEqual(guard.check(note, FACTS), ["headline: malformed claims"])
        self.assertEqual(guard.check(with_bullet("{AAPL.move_1d}.", ["leader"]), FACTS), ["bullet 1: malformed"])

    def test_tie_must_name_every_tied_stock(self):
        prices = _prices()
        prices.loc[DATES[-1], "NVDA"] = 110.0  # NVDA +10.0% too, tying Apple
        facts = build_facts(prices, "2025-01-02")
        one = with_bullet("{AAPL.move_1d}, the best in the group.", [{"type": "leader", "ids": ["AAPL"]}])
        self.assertTrue(any("is false" in p for p in guard.check(one, facts)))
        both = with_bullet("{AAPL.move_1d} and {NVDA.move_1d}, the best in the group.",
                           [{"type": "leader", "ids": ["NVDA", "AAPL"]}])
        note_ok = copy.deepcopy(both)
        note_ok["headline"] = "Apple and Nvidia led a quiet session"  # a tie: "Apple led" alone would mislead
        note_ok["headline_claims"] = [{"type": "leader", "ids": ["AAPL", "NVDA"]}]
        self.assertEqual(guard.check(note_ok, facts), [])


class GuardWithRealNumberCheck(unittest.TestCase):
    """Uses Zak's find_banned_numbers. Fails until numbers.py is written."""

    def test_spelled_out_numbers_are_rejected(self):
        problems = guard.check(with_bullet("{AAPL.move_1d}, two percent more than {MSFT.change_1d}."), FACTS)
        self.assertTrue(any("numbers must come from placeholders" in p for p in problems), problems)

    def test_the_good_note_passes(self):
        self.assertEqual(guard.check(GOOD, FACTS), [])


if __name__ == "__main__":
    unittest.main()
