"""Run the note evals.

    python evals/run_evals.py --label baseline              live: one note per case (costs money)
    python evals/run_evals.py --label baseline --judge      ...and score each note with a judge model
    python evals/run_evals.py --regrade evals/results/X.json  re-grade saved notes (free)
    python evals/run_evals.py --estimate                    print the expected cost and stop

Live runs need ANTHROPIC_API_KEY in the environment. Results are saved to
evals/results/<date>-<label>.json with the notes, grades, scores, settings and
cost, so any change to the prompt, model or settings can be compared before and
after.

Release gate (code only): every case passes the guard and every tagged claim
matches the independently worked-out answers. The judge's scores are reported
and tracked, but don't gate a release.
"""

import argparse
import datetime as dt
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "src"))
sys.path.insert(0, str(HERE))

from grade import grade, summary  # noqa: E402
from m7.note import write  # noqa: E402

CASES = HERE / "cases"
RESULTS = HERE / "results"

# US dollars per million tokens (input, output), from Anthropic's published prices.
PRICES = {"claude-opus-5-5": (4.00, 20.00), "claude-sonnet-5-5": (2.00, 10.00)}
JUDGE_MODEL = "claude-sonnet-5-5"
# Rough sizes for --estimate, per call: (input, output) tokens.
WRITER_TOKENS = (2500, 800)
JUDGE_TOKENS = (1200, 300)

JUDGE_SYSTEM = """\
You review a short daily stock-market note written for non-experts. You get the note \
as published and the fact sheet it was written from. Every number in the note was \
filled in by code from the fact sheet, so don't check arithmetic. Score two things \
from 1 (poor) to 5 (excellent):

clarity: would a reader with no finance background understand it on one read? \
Plain words, short sentences, no jargon, a headline that says what happened.
tone: is it calm, neutral and descriptive? No hype, no drama, no hints about what \
to do or what comes next.

Give a one-sentence reason for each score."""

JUDGE_SCHEMA = {
    "type": "object",
    "properties": {
        "clarity": {"type": "integer", "enum": [1, 2, 3, 4, 5]},
        "clarity_reason": {"type": "string"},
        "tone": {"type": "integer", "enum": [1, 2, 3, 4, 5]},
        "tone_reason": {"type": "string"},
    },
    "required": ["clarity", "clarity_reason", "tone", "tone_reason"],
    "additionalProperties": False,
}


def load_cases():
    return [json.loads(p.read_text(encoding="utf-8")) for p in sorted(CASES.glob("*.json"))]


def cost(model, input_tokens, output_tokens):
    price_in, price_out = PRICES[model]
    return ((input_tokens or 0) * price_in + (output_tokens or 0) * price_out) / 1e6


def estimate(n_cases, judge):
    writer = n_cases * cost(write.MODEL, *WRITER_TOKENS)
    judged = n_cases * cost(JUDGE_MODEL, *JUDGE_TOKENS) if judge else 0.0
    return writer + judged


def judge_note(client, shown, facts):
    request = {
        "model": JUDGE_MODEL,
        "max_tokens": 2000,
        "system": JUDGE_SYSTEM,
        "messages": [{"role": "user", "content": json.dumps({
            "note": {"headline": shown["headline"], "bullets": shown["bullets"]},
            "fact_sheet": {k: v["text"] for k, v in facts["facts"].items()},
        }, indent=1)}],
        "output_config": {"effort": "low", "format": {"type": "json_schema", "schema": JUDGE_SCHEMA}},
    }
    response = client.messages.create(**request)
    usage = (response.usage.input_tokens, response.usage.output_tokens)
    if response.stop_reason != "end_turn":
        return {"error": f"judge stopped with {response.stop_reason}"}, usage
    text = next((b.text for b in response.content if b.type == "text"), "{}")
    return json.loads(text), usage


def run_live(cases, client, use_judge):
    rows, spend = [], 0.0
    for case in cases:
        row = {"case": case["id"], "why": case["why"]}
        try:
            note, meta = write.write_note(case["facts"], client)
            row.update(note=note, meta=meta)
            spend += cost(meta["model"] if meta["model"] in PRICES else write.MODEL,
                          meta["input_tokens"], meta["output_tokens"])
            row["grade"] = grade(note, case)
        except write.NoteFailed as err:
            row.update(note=None, meta=err.meta, error=str(err))
            row["grade"] = {"case": case["id"], "why": case["why"], "guard_problems": [str(err)],
                            "claims": 0, "claim_errors": [], "passed": False, "shown": None}
        if use_judge and row["grade"]["passed"]:
            scores, usage = judge_note(client, row["grade"]["shown"], case["facts"])
            row["judge"] = scores
            spend += cost(JUDGE_MODEL, *usage)
        rows.append(row)
        mark = "pass" if row["grade"]["passed"] else "FAIL"
        print(f"{case['id']}  {mark}  {case['why']}")
    return rows, spend


def report(rows, spend, label, use_judge):
    grades = [r["grade"] for r in rows]
    result = {
        "label": label,
        "run_at": dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%MZ"),
        "settings": {"model": write.MODEL, "effort": write.EFFORT, "prompt_version": write.PROMPT_VERSION,
                     "judge_model": JUDGE_MODEL if use_judge else None},
        "summary": summary(grades),
        "cost_usd": round(spend, 4),
        "rows": rows,
    }
    judged = [r["judge"] for r in rows if isinstance(r.get("judge"), dict) and "clarity" in r["judge"]]
    if judged:
        result["summary"]["judge"] = {
            "notes_scored": len(judged),
            "clarity_avg": round(sum(j["clarity"] for j in judged) / len(judged), 2),
            "tone_avg": round(sum(j["tone"] for j in judged) / len(judged), 2),
            "lowest": min(min(j["clarity"], j["tone"]) for j in judged),
        }
    return result


def print_summary(result):
    s = result["summary"]
    print(f"\n{s['passed']}/{s['cases']} passed  ·  guard failures {s['guard_failures']}  ·  "
          f"claims wrong {s['claims_wrong']} of {s['claims_tagged']}  ·  cost ${result['cost_usd']:.2f}")
    if "judge" in s:
        j = s["judge"]
        print(f"judge: clarity {j['clarity_avg']}, tone {j['tone_avg']}, lowest {j['lowest']} ({j['notes_scored']} notes)")
    print("release gate:", "MET" if s["release_gate_met"] else "NOT MET")
    for row in result["rows"]:
        g = row["grade"]
        if not g["passed"]:
            print(f"  {g['case']}: {'; '.join(g['guard_problems'] + g['claim_errors'])}")


def save(result):
    RESULTS.mkdir(exist_ok=True)
    path = RESULTS / f"{result['run_at'][:10]}-{result['label']}.json"
    path.write_text(json.dumps(result, indent=1, default=str), encoding="utf-8")
    return path


def regrade(path):
    old = json.loads(Path(path).read_text(encoding="utf-8"))
    cases = {c["id"]: c for c in load_cases()}
    rows = []
    for row in old["rows"]:
        if row.get("note") is not None and row["case"] in cases:
            row = {**row, "grade": grade(row["note"], cases[row["case"]])}
        rows.append(row)
    result = report(rows, 0.0, old["label"] + "-regraded", "judge" in old["summary"])
    result["settings"] = old["settings"]
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--label", default="run")
    parser.add_argument("--judge", action="store_true", help="also score notes with the judge model")
    parser.add_argument("--regrade", metavar="RESULTS_JSON", help="re-grade saved notes without calling the API")
    parser.add_argument("--estimate", action="store_true", help="print the expected cost and stop")
    parser.add_argument("--limit", type=int, help="only the first N cases")
    args = parser.parse_args(argv)

    cases = load_cases()[: args.limit] if args.limit else load_cases()
    if args.estimate:
        print(f"{len(cases)} cases: about ${estimate(len(cases), args.judge):.2f}"
              + (" including the judge" if args.judge else ""))
        return 0
    if args.regrade:
        result = regrade(args.regrade)
    else:
        rows, spend = run_live(cases, write._client(), args.judge)
        result = report(rows, spend, args.label, args.judge)
    print_summary(result)
    print("saved", save(result).relative_to(HERE.parent))
    return 0 if result["summary"]["release_gate_met"] else 1


if __name__ == "__main__":
    sys.exit(main())
