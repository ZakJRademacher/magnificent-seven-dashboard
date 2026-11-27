"""Grade one written note against its eval case. Code only, no model.

    grade(note, case) -> dict

Two checks, both required for a note to count as passing:
1. the guard (the same check that runs before publishing) finds no problems;
2. every tagged claim matches the case's expected answers, which were worked out
   independently of the fact sheet when the case was made (see make_cases.py).
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from m7.note.guard import check  # noqa: E402
from m7.note.render import UnknownFact, render  # noqa: E402

# Tag types whose ids must name exactly the expected stocks.
NAMED = {"leader": "leader", "laggard": "laggard", "biggest_mover": "biggest_mover",
         "only_up": "up", "only_down": "down"}
# Tag types that are simply true or false for the day.
FLAGS = {"all_up", "all_down", "most_up", "most_down", "group_beat_spy", "group_trailed_spy"}


def claim_errors(note, expected):
    """(number of tagged claims, list of the wrong ones with the reason)."""
    tagged = list(note.get("headline_claims") or [])
    for bullet in note.get("bullets") or []:
        tagged += list(bullet.get("claims") or [])
    errors = []
    for claim in tagged:
        kind, ids = claim.get("type"), sorted(claim.get("ids") or [])
        if kind in NAMED:
            want = expected[NAMED[kind]]
            if ids != want:
                errors.append(f"{kind} named {ids}, expected {want}")
        elif kind in FLAGS:
            if not expected[kind]:
                errors.append(f"{kind} is not true on this day")
        else:
            errors.append(f"unknown claim type {kind!r}")
    return len(tagged), errors


def grade(note, case):
    problems = check(note, case["facts"])
    n_claims, wrong = claim_errors(note, case["expected"]) if isinstance(note, dict) else (0, ["not a note"])
    try:
        shown = render(note, case["facts"]) if not problems else None
    except (UnknownFact, KeyError, TypeError):
        shown = None
    return {
        "case": case["id"],
        "why": case["why"],
        "guard_problems": problems,
        "claims": n_claims,
        "claim_errors": wrong,
        "passed": not problems and not wrong,
        "shown": shown,
    }


def summary(grades):
    n = len(grades)
    passed = sum(g["passed"] for g in grades)
    claims = sum(g["claims"] for g in grades)
    wrong = sum(len(g["claim_errors"]) for g in grades)
    guard_fail = sum(bool(g["guard_problems"]) for g in grades)
    return {
        "cases": n,
        "passed": passed,
        "pass_rate": passed / n if n else 0.0,
        "guard_failures": guard_fail,
        "claims_tagged": claims,
        "claims_wrong": wrong,
        "release_gate_met": n > 0 and passed == n,
    }
