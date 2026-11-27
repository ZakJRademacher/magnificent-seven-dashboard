"""Ask an AI model to write the day's note from the fact sheet.

The model sees only fact ids with their already-rendered text, and the list of
checkable claims. It answers in a fixed JSON shape and refers to figures by
placeholder, so it never types a number. Its answer is not trusted: the guard
(guard.check) decides whether it can be published.

    write_note(facts, client=None) -> (note, meta)

`client` is an anthropic.Anthropic instance; tests pass a stand-in. The SDK is
imported only when a real client is needed, so the rest of the pipeline and the
tests don't depend on it.
"""

import json

from ..config import BENCHMARK, TICKERS

MODEL = "claude-opus-5-5"
EFFORT = "medium"        # the evals decide whether "low" holds quality
MAX_TOKENS = 4000
TIMEOUT_SECONDS = 120
PROMPT_VERSION = "4"
# v2: number words like "seven" and "two" named as off-limits; full sentences.
# v3: no repeating what a placeholder already says; higher/lower named; length guidance.
# v4: a {T.change_*} placeholder (no company name) only after that company is named in the same sentence.

CLAIM_TYPES = [
    "leader", "laggard", "biggest_mover", "only_up", "only_down",
    "all_up", "all_down", "most_up", "most_down", "group_beat_spy", "group_trailed_spy",
]

_CLAIM = {
    "type": "object",
    "properties": {
        "type": {"type": "string", "enum": CLAIM_TYPES},
        "ids": {"type": "array", "items": {"type": "string", "enum": TICKERS + [BENCHMARK]}},
    },
    "required": ["type", "ids"],
    "additionalProperties": False,
}
SCHEMA = {
    "type": "object",
    "properties": {
        "headline": {"type": "string"},
        "headline_claims": {"type": "array", "items": _CLAIM},
        "bullets": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {"text": {"type": "string"}, "claims": {"type": "array", "items": _CLAIM}},
                "required": ["text", "claims"],
                "additionalProperties": False,
            },
        },
    },
    "required": ["headline", "headline_claims", "bullets"],
    "additionalProperties": False,
}

SYSTEM = """\
You write a short daily note for a public dashboard about seven large US tech stocks \
(Apple, Microsoft, Alphabet, Amazon, Nvidia, Meta, Tesla) and the S&P 500 fund (SPY). \
Readers are not finance experts.

You get a fact sheet: fact ids with their exact wording, and a list of claims that are true today.

Write one headline (at most about ten words) and exactly three bullets.

Rules for every word you write:
- Every figure and every direction of movement comes from a placeholder: write {fact_id} and it \
will be replaced by that fact's wording. Never type a number, a percentage, a price, a date, or a \
spelled-out number, and never write words like rose, fell, gained, lost, up, down, higher, lower, \
flat or unchanged yourself: use the placeholder, which already says the direction.
- {T.move_1d} includes the company name; {T.change_1d}, {T.change_5d} and {T.change_ytd} don't. \
Use a change placeholder only after the same company has been named earlier in the same sentence \
("{AAPL.move_1d}, leaving it {AAPL.change_ytd}"), never after another company or in a new \
sentence that starts "It" or "The stock". To mention a second company, use its move placeholder.
- Read each placeholder's wording before using it and don't repeat what it already says: \
{group.move_1d} already ends "on average", and {group.gap_to_spy_1d} already names the S&P 500 \
fund, so don't add "on average" or name the fund again in the same sentence.
- Describe what happened. Do not predict, give reasons that are not in the facts, give advice, or \
say anything about what investors should do.
- Words such as best, led, worst, lagged, biggest, all, every, most, only, ahead, behind, beat or \
trailed state a claim. Use them only when that claim is in today's true claims, and list it in the \
claims for that headline or bullet, with every stock it covers (ties name all tied stocks).
- Number words count as numbers too: never write seven, two, three, half, dozen, or any other \
number word. Call the stocks "the group" or "the Magnificent Seven", never \
"the seven". To say how many rose, fell or were flat, use {count.up}, {count.down} or {count.flat}.
- Name only these companies, by their usual names or tickers. Plain, calm wording; no hype.
- Each bullet uses at least one placeholder and is made of complete sentences (a list of \
placeholders on its own is not a sentence). Keep each bullet to one or two short sentences, about \
thirty words once the placeholders are filled in; you don't need to mention every stock. A placeholder that starts a sentence is capitalised for you.

Example bullet text: "{NVDA.move_1d}, the best result in the group." with claims \
[{"type": "leader", "ids": ["NVDA"]}] when Nvidia is today's only leader.
"""


class NoteFailed(RuntimeError):
    """The model didn't return a usable note (refusal, cut off, or not JSON). `meta` says what came back."""

    def __init__(self, message, meta=None):
        super().__init__(message)
        self.meta = meta or {}


def prompt_input(facts):
    """What the model sees: fact ids with wording, and today's true claims. No outside text."""
    c = facts["claims"]
    true_claims = {
        "leader": c["best_1d"], "laggard": c["worst_1d"], "biggest_mover": c["biggest_mover_1d"],
        "up": c["up"], "down": c["down"], "flat": c["flat"],
        "all_up": c["all_up"], "all_down": c["all_down"],
        "most_up": len(c["up"]) >= 4, "most_down": len(c["down"]) >= 4,
        "only_up": c["up"] if 0 < len(c["up"]) < 7 else None,
        "only_down": c["down"] if 0 < len(c["down"]) < 7 else None,
        "group_beat_spy": c["group_beat_spy"], "group_trailed_spy": c["group_trailed_spy"],
    }
    return json.dumps({
        "date": facts["facts"]["date"]["text"],
        "facts": {fid: f["text"] for fid, f in facts["facts"].items()},
        "true_claims": true_claims,
    }, indent=1)


def build_request(facts):
    return {
        "model": MODEL,
        "max_tokens": MAX_TOKENS,
        "system": SYSTEM,
        "messages": [{"role": "user", "content": "Today's fact sheet:\n" + prompt_input(facts)}],
        "output_config": {"effort": EFFORT, "format": {"type": "json_schema", "schema": SCHEMA}},
    }


def _client():
    import anthropic

    return anthropic.Anthropic(timeout=TIMEOUT_SECONDS, max_retries=2)


def write_note(facts, client=None):
    """One request. Returns (note, meta); raises NoteFailed when there is no usable note."""
    client = client or _client()
    response = client.messages.create(**build_request(facts))
    meta = {
        "model": getattr(response, "model", MODEL),
        "prompt_version": PROMPT_VERSION,
        "effort": EFFORT,
        "request_id": getattr(response, "_request_id", None),
        "input_tokens": getattr(response.usage, "input_tokens", None),
        "output_tokens": getattr(response.usage, "output_tokens", None),
        "stop_reason": response.stop_reason,
    }
    if response.stop_reason != "end_turn":
        raise NoteFailed(f"the model stopped with {response.stop_reason!r}", meta)
    text = next((b.text for b in response.content if b.type == "text"), None)
    try:
        note = json.loads(text)
    except (TypeError, ValueError) as err:
        raise NoteFailed(f"the answer was not JSON ({err})", meta) from None
    return note, meta
