"""The eval cases, grader and runner, exercised offline with a stand-in model (no key, no cost)."""

import json
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "evals"))

import run_evals  # noqa: E402
from grade import claim_errors, grade  # noqa: E402

CASES = run_evals.load_cases()


def names(ids, key):
    return " and ".join("{" + f"{t}.{key}" + "}" for t in ids)


def honest_note(case):
    """A note built only from the case's true claims: what a well-behaved writer returns."""
    c = case["facts"]["claims"]
    best, worst = c["best_1d"], c["worst_1d"]
    return {
        "headline": "{group.move_1d}",
        "headline_claims": [],
        "bullets": [
            {"text": names(best, "move_1d") + ", the best result in the group.",
             "claims": [{"type": "leader", "ids": best}]},
            {"text": names(worst, "move_1d") + ", the weakest result in the group.",
             "claims": [{"type": "laggard", "ids": worst}]},
            {"text": "Overall, {count.up}, and {count.down}.", "claims": []},
        ],
    }


class StandInModel:
    """Answers writer requests with an honest note (or a wrong one for chosen cases) and judge requests with scores."""

    def __init__(self, wrong_leader_on=()):
        self.wrong_leader_on = set(wrong_leader_on)
        self.messages = self
        self.calls = {"writer": 0, "judge": 0}

    def create(self, **request):
        if request["model"] == run_evals.JUDGE_MODEL:
            self.calls["judge"] += 1
            body = {"clarity": 4, "clarity_reason": "clear", "tone": 5, "tone_reason": "calm"}
        else:
            self.calls["writer"] += 1
            sent = json.loads(request["messages"][0]["content"].split("\n", 1)[1])
            case = next(c for c in CASES if c["facts"]["facts"]["date"]["text"] == sent["date"])
            body = honest_note(case)
            if case["id"] in self.wrong_leader_on:
                body["bullets"][0]["claims"] = [{"type": "leader", "ids": ["TSLA"]}]
        return SimpleNamespace(model=request["model"], stop_reason="end_turn", _request_id="req_x",
                               usage=SimpleNamespace(input_tokens=2000, output_tokens=500),
                               content=[SimpleNamespace(type="text", text=json.dumps(body))])


class Cases(unittest.TestCase):
    def test_thirty_frozen_cases_covering_every_situation(self):
        self.assertEqual(len(CASES), 30)
        reasons = {c["why"] for c in CASES}
        for needed in ["first trading day of a year", "all seven up", "all seven down", "tie for best or worst",
                       "very large single-stock move", "two or more flat stocks",
                       "first day after a market holiday", "group level with SPY", "ordinary day"]:
            self.assertIn(needed, reasons)

    def test_expected_answers_agree_with_the_fact_sheet(self):
        pairs = {"leader": "best_1d", "laggard": "worst_1d", "biggest_mover": "biggest_mover_1d", "up": "up",
                 "down": "down", "flat": "flat", "all_up": "all_up", "all_down": "all_down",
                 "group_beat_spy": "group_beat_spy", "group_trailed_spy": "group_trailed_spy"}
        for case in CASES:
            for exp_key, fact_key in pairs.items():
                with self.subTest(case=case["id"], claim=exp_key):
                    self.assertEqual(case["expected"][exp_key], case["facts"]["claims"][fact_key])


class Grader(unittest.TestCase):
    def test_an_honest_note_passes_on_every_case(self):
        for case in CASES:
            with self.subTest(case=case["id"]):
                g = grade(honest_note(case), case)
                self.assertTrue(g["passed"], g["guard_problems"] + g["claim_errors"])

    def test_a_wrong_claim_is_caught_even_if_the_fact_sheet_agreed(self):
        case = CASES[0]
        note = honest_note(case)
        wrong = [t for t in ["AAPL", "MSFT", "TSLA"] if t not in case["expected"]["leader"]][:1]
        note["bullets"][0]["claims"] = [{"type": "leader", "ids": wrong}]
        n, errors = claim_errors(note, case["expected"])
        self.assertEqual(n, 2)
        self.assertEqual(len(errors), 1)
        self.assertIn("leader named", errors[0])

    def test_a_false_flag_is_caught(self):
        case = next(c for c in CASES if c["why"] == "all seven down")
        _, errors = claim_errors({"bullets": [{"claims": [{"type": "all_up"}]}]}, case["expected"])
        self.assertEqual(errors, ["all_up is not true on this day"])


class Runner(unittest.TestCase):
    def test_a_clean_run_meets_the_release_gate_and_costs_what_the_tokens_say(self):
        model = StandInModel()
        rows, spend = run_evals.run_live(CASES[:5], model, use_judge=True)
        result = run_evals.report(rows, spend, "test", True)
        self.assertTrue(result["summary"]["release_gate_met"])
        self.assertEqual(model.calls, {"writer": 5, "judge": 5})
        # Writer: 5 x (2000 x $4 + 500 x $20) / 1M = $0.09. Judge: 5 x (2000 x $2 + 500 x $10) / 1M = $0.045.
        self.assertAlmostEqual(spend, 0.135, places=6)
        self.assertEqual(result["summary"]["judge"]["clarity_avg"], 4.0)

    def test_one_wrong_note_fails_the_gate_and_is_not_judged(self):
        bad = CASES[2]["id"]
        model = StandInModel(wrong_leader_on=[bad])
        rows, _ = run_evals.run_live(CASES[:5], model, use_judge=True)
        result = run_evals.report(rows, 0.0, "test", True)
        self.assertFalse(result["summary"]["release_gate_met"])
        self.assertEqual(result["summary"]["passed"], 4)
        self.assertEqual(model.calls["judge"], 4)

    def test_the_estimate_is_under_a_dollar_for_a_full_run_with_the_judge(self):
        self.assertLess(run_evals.estimate(30, judge=True), 1.0)


if __name__ == "__main__":
    unittest.main()
