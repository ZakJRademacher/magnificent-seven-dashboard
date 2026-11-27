"""Spec for find_banned_numbers: the writer may not type any number itself."""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from m7.note.numbers import find_banned_numbers  # noqa: E402


class Clean(unittest.TestCase):
    def test_plain_prose_is_clean(self):
        self.assertEqual(find_banned_numbers("  and led the group, while   lagged behind."), [])

    def test_words_that_merely_contain_a_number_are_clean(self):
        for text in ["often", "someone", "tone", "weight", "phone", "content", "network-wide"]:
            with self.subTest(text=text):
                self.assertEqual(find_banned_numbers(text), [])

    def test_the_name_magnificent_seven_is_allowed(self):
        self.assertEqual(find_banned_numbers("The Magnificent Seven had a mixed day"), [])
        self.assertEqual(find_banned_numbers("the magnificent seven"), [])


class Digits(unittest.TestCase):
    def test_any_digit(self):
        for text, found in [("up 3", ["3"]), ("in 2026", ["2026"]), ("Q3 results", ["3"]), ("its 3rd gain", ["3"])]:
            with self.subTest(text=text):
                self.assertEqual(find_banned_numbers(text), found)

    def test_decimals_and_several_numbers(self):
        self.assertEqual(find_banned_numbers("between 2.5 and 4"), ["2", "5", "4"])


class SymbolsAndUnits(unittest.TestCase):
    def test_symbols(self):
        self.assertEqual(find_banned_numbers("a % move"), ["%"])
        self.assertEqual(find_banned_numbers("about $ a share"), ["$"])

    def test_unit_words(self):
        self.assertEqual(find_banned_numbers("a few percent"), ["percent"])
        self.assertEqual(find_banned_numbers("a few per cent"), ["per cent"])
        self.assertEqual(find_banned_numbers("a percentage gain"), ["percentage"])
        self.assertEqual(find_banned_numbers("some basis points"), ["basis", "points"])


class SpelledOut(unittest.TestCase):
    def test_small_numbers_and_tens(self):
        for word in ["zero", "one", "two", "seven", "twelve", "nineteen", "twenty", "forty", "ninety"]:
            with self.subTest(word=word):
                self.assertEqual(find_banned_numbers(f"rose {word} times"), [word])

    def test_large_numbers_and_fractions(self):
        for word in ["hundred", "thousand", "million", "billion", "trillion",
                     "half", "halves", "quarter", "dozen", "double", "triple", "twice"]:
            with self.subTest(word=word):
                self.assertEqual(find_banned_numbers(f"a {word} gain"), [word])

    def test_case_is_ignored_and_the_original_text_is_returned(self):
        self.assertEqual(find_banned_numbers("SEVEN stocks"), ["SEVEN"])
        self.assertEqual(find_banned_numbers("Two of them"), ["Two"])

    def test_hyphenated_words_count(self):
        self.assertEqual(find_banned_numbers("a seven-stock group"), ["seven"])

    def test_magnificent_seven_does_not_excuse_another_seven(self):
        self.assertEqual(find_banned_numbers("all seven of the Magnificent Seven"), ["seven"])


class Dates(unittest.TestCase):
    def test_months_and_weekdays(self):
        self.assertEqual(find_banned_numbers("on Monday in November"), ["Monday", "November"])
        self.assertEqual(find_banned_numbers("since january"), ["january"])


if __name__ == "__main__":
    unittest.main()
