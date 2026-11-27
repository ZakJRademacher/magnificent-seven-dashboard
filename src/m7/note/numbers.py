"""Find numbers the writer typed itself.

Every figure in the note must come from a placeholder, so the writer's own words
(the text with placeholders already removed) may not contain any number at all.

    find_banned_numbers(text) -> list of the offending pieces of text, in order

What counts as a number here (tests/test_note_numbers.py is the full spec):
- any digit: "3", "2026", "Q3", "3rd"
- the symbols "%" and "$"
- the words "percent", "per cent", "percentage", "points", "basis"
- spelled-out numbers: zero to twenty, thirty, forty, ... ninety, hundred,
  thousand, million, billion, trillion, plus half, halves, quarter, dozen,
  double, triple, twice
- month names (January ... December) and weekday names (Monday ... Sunday):
  dates come from the {date} placeholder
Whole words only, ignoring case ("often" is fine, "SEVEN" is not); hyphenated
words count ("seven-stock"); the name "Magnificent Seven" is allowed.
"""

import re

SPELLED = (
    "zero one two three four five six seven eight nine ten eleven twelve thirteen fourteen fifteen "
    "sixteen seventeen eighteen nineteen twenty thirty forty fifty sixty seventy eighty ninety "
    "hundred thousand million billion trillion half halves quarter dozen double triple twice"
)
UNITS = "percent percentage points basis"
MONTHS = "january february march april may june july august september october november december"
WEEKDAYS = "monday tuesday wednesday thursday friday saturday sunday"

WORDS = " ".join([SPELLED, UNITS, MONTHS, WEEKDAYS]).split()

# Digit runs, the two symbols, "per cent", then any listed word standing on its own.
# \b treats a hyphen as a word edge, so "seven-stock" yields "seven".
BANNED = re.compile(r"\d+|%|\$|\bper\s+cent\b|\b(?:" + "|".join(WORDS) + r")\b", re.IGNORECASE)

# The dashboard's own name. Blanked out (same length) before searching, so another
# "seven" in the same text is still caught.
ALLOWED = re.compile(r"\bmagnificent\s+seven\b", re.IGNORECASE)


def find_banned_numbers(text):
    text = ALLOWED.sub(lambda m: " " * len(m.group()), text)
    return BANNED.findall(text)
