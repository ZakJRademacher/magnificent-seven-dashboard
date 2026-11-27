"""The daily note's step in the pipeline run.

    note_step(state_dir, prices, mode, now_iso, client=None, prices_ok=True)
        -> (check or None, site note or None, ledger info or None)

Modes:
    live     scheduled and manual runs on main: write a note for the latest day if there isn't
             one for exactly these facts yet (one API call), then publish it
    saved    other production runs (pushes to main): no API call, republish the saved note
    example  dry runs: show the saved example note, never touch the saved one
    off      no note at all

The last good note is kept in the pipeline state as note.json, with the hash of the facts it
was written from. Before any saved note is shown again it is rebuilt from the current prices
and re-checked by the guard, so a restatement can't leave a stale claim on the page.

A note problem is never allowed to stop the prices: every failure becomes a non-blocking
`note` warning, and the previous note stays up.
"""

import json
from pathlib import Path

from ..checks import Check
from . import write
from .example import example_payload
from .facts import build_facts
from .guard import check
from .render import payload

MODES = ("live", "saved", "example", "off")
STATE_FILE = "note.json"
DETAIL_MAX = 300


def _warn(detail):
    detail = detail if len(detail) <= DETAIL_MAX else detail[: DETAIL_MAX - 1] + "…"
    return Check("note", "warn", detail, blocks=False)


def _pass(detail):
    return Check("note", "pass", detail, blocks=False)


def load_saved(state_dir):
    path = Path(state_dir) / STATE_FILE
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except ValueError:
        return None


def publishable(saved, prices):
    """The saved note as the page should show it, rebuilt from the current prices, or None
    when it can't be shown any more (its day is gone, or a claim is no longer true)."""
    if not saved:
        return None
    try:
        facts = build_facts(prices, saved["as_of"])
        if check(saved["note"], facts):
            return None
        return payload(saved["note"], facts, generated=saved.get("generated"))
    except (KeyError, TypeError, ValueError):
        return None


def note_step(state_dir, prices, mode, now_iso, client=None, prices_ok=True):
    if mode not in MODES:
        raise ValueError(f"unknown note mode {mode!r}")
    if mode == "off":
        return None, None, None
    if mode == "example":
        try:
            return _pass("example note (dry run: no API call)"), example_payload(prices), None
        except (SystemExit, KeyError, ValueError) as err:
            return _warn(f"example note unavailable: {err}"), None, None

    saved = load_saved(state_dir)
    if mode == "saved":
        if not saved:
            return None, None, None
        shown = publishable(saved, prices)
        if shown is None:
            return _warn(f"the saved note for {saved.get('as_of')} no longer matches the data; not shown"), None, None
        return _pass(f"kept the note for {saved['as_of']} (this run doesn't write notes)"), shown, None

    # live
    if not prices_ok:
        return _warn("not written: the price data didn't publish on this run"), publishable(saved, prices), None
    try:
        facts = build_facts(prices)
    except ValueError as err:
        return _warn(f"no fact sheet for the latest day: {err}"), publishable(saved, prices), None
    if saved and saved.get("as_of") == facts["as_of"] and saved.get("facts_hash") == facts["hash"]:
        shown = publishable(saved, prices)
        if shown is not None:
            return _pass(f"already written for {facts['as_of']}"), shown, None

    try:
        note, meta = write.write_note(facts, client)
    except write.NoteFailed as err:
        info = {"status": "failed", "as_of": facts["as_of"], **err.meta}
        return _warn(f"not written: {err}"), publishable(saved, prices), info
    except Exception as err:  # network, auth, rate limits, a missing key: never fatal to the run
        info = {"status": "failed", "as_of": facts["as_of"], "error": type(err).__name__}
        return _warn(f"not written: {type(err).__name__}: {err}"), publishable(saved, prices), info

    problems = check(note, facts)
    if problems:
        info = {"status": "rejected", "as_of": facts["as_of"], "problems": problems, **meta}
        return _warn("rejected by the guard: " + "; ".join(problems)), publishable(saved, prices), info

    record = {"as_of": facts["as_of"], "facts_hash": facts["hash"], "generated": now_iso, "note": note, "meta": meta}
    path = Path(state_dir) / STATE_FILE
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(record, indent=1), encoding="utf-8")
    info = {"status": "written", "as_of": facts["as_of"], **meta}
    detail = f"written for {facts['as_of']} ({meta['model']}, {meta['input_tokens']} in / {meta['output_tokens']} out tokens)"
    return _pass(detail), payload(note, facts, generated=now_iso), info
