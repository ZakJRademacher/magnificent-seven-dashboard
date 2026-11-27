"""Write site/note.json from the saved example response, for dry runs and local previews.

    python -m m7.note.example --site site

No API call. The note is checked by the guard like a real one, and marked
"example" so the page labels it.
"""

import argparse
import json
import sys
from pathlib import Path

import pandas as pd

from ..config import PRICES_CSV, ROOT
from .facts import build_facts
from .guard import check
from .render import payload

EXAMPLE = Path(__file__).with_name("example_response.json")


def load_example():
    return json.loads(EXAMPLE.read_text(encoding="utf-8"))


def example_payload(prices=None):
    saved = load_example()
    prices = prices if prices is not None else pd.read_csv(PRICES_CSV, index_col="Date", parse_dates=True)
    facts = build_facts(prices, saved["as_of"])
    problems = check(saved["note"], facts)
    if problems:
        raise SystemExit("The saved example note fails the guard: " + "; ".join(problems))
    return payload(saved["note"], facts, generated=None, example=True)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--site", type=Path, default=ROOT / "site")
    args = parser.parse_args(argv)
    args.site.mkdir(parents=True, exist_ok=True)
    (args.site / "note.json").write_text(json.dumps(example_payload(), indent=1), encoding="utf-8")
    print(f"Wrote {args.site / 'note.json'} (example)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
