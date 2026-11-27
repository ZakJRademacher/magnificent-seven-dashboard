"""Check a written note against the fact sheet before it can be published.

    check(note, facts) -> list of problems (empty means the note may be published)

The writer's own words (everything outside placeholders) may not contain numbers,
direction words, unverified superlatives, advice or predictions, or names other
than the eight known series. Claims that can't be expressed as a placeholder
("led the group", "all seven rose") must be tagged, and each tag is checked
against the facts.
"""

import re

from .facts import NAMES
from .numbers import find_banned_numbers
from .render import UnknownFact, placeholders, render, strip_placeholders

HEADLINE_MAX = 90
BULLET_MAX = 200
BULLETS = 3

# Words that state a direction or size of move. These must come from placeholders.
DIRECTION = {
    "rose", "rise", "rises", "rising", "risen", "fell", "fall", "falls", "falling", "fallen",
    "gained", "gain", "gains", "gaining", "lost", "lose", "loses", "losing", "loss", "losses",
    "up", "down", "higher", "lower", "climbed", "climb", "dropped", "drop", "drops", "slid", "slipped",
    "rallied", "rally", "jumped", "jump", "surged", "surge", "soared", "sank", "tumbled", "plunged",
    "declined", "decline", "advanced", "advance", "rebounded", "rebound", "flat", "unchanged",
    "slide", "slides", "sliding", "selloff", "sell-off", "retreat", "retreated", "pullback", "dip", "dipped",
    "rallies", "recovered", "recovery", "slump", "slumped", "spiked", "crashed", "crash", "weaker", "stronger",
}

# Direction words a verified group-direction claim can back up: "the only stock to fall" is
# fine when the bullet carries a true only_down claim. Everything else in DIRECTION
# (and "flat"/"unchanged") still has to come from a placeholder.
UP_WORDS = {"rose", "rise", "rises", "rising", "risen", "gained", "gain", "gains", "gaining", "up", "higher",
            "climbed", "climb", "advanced", "advance"}
DOWN_WORDS = {"fell", "fall", "falls", "falling", "fallen", "lost", "lose", "loses", "losing", "loss", "losses",
              "down", "lower", "declined", "decline", "dropped", "drop", "drops", "slipped", "dip", "dipped"}
UP_CLAIMS = {"only_up", "all_up", "most_up"}
DOWN_CLAIMS = {"only_down", "all_down", "most_down"}

# Claims that need a tag, and the tag types that can support them.
NEEDS_TAG = {
    "leader": ({"best", "top", "led", "leading", "leader", "strongest", "highest"}, {"leader"}),
    "laggard": ({"worst", "bottom", "lagged", "lagging", "laggard", "weakest", "lowest"}, {"laggard"}),
    "biggest": ({"biggest", "largest", "smallest"}, {"biggest_mover"}),
    "all": ({"all", "every"}, {"all_up", "all_down"}),
    "most": ({"most", "majority"}, {"most_up", "most_down"}),
    "only": ({"only", "alone"}, {"only_up", "only_down"}),
    "vs_spy": ({"outperformed", "underperformed", "beat", "trailed", "ahead", "behind"},
               {"group_beat_spy", "group_trailed_spy"}),
}

# Never allowed: advice, predictions, and claims the data can't support.
BANNED = {
    "buy", "sell", "hold", "should", "recommend", "recommends", "recommended", "advise", "expect",
    "expects", "expected", "will", "would", "could", "might", "likely", "unlikely", "target",
    "forecast", "outlook", "opportunity", "bullish", "bearish", "momentum", "because", "due",
    "investors", "record", "ever", "never", "always", "historic", "guaranteed",
}

CLAIM_TYPES = {t for _, types in NEEDS_TAG.values() for t in types}

ALLOWED_NAMES = set(NAMES) | {n for name in NAMES.values() for n in re.findall(r"[A-Za-z&]+", name)} | {
    "Magnificent", "Seven", "S&P",
}

WORD = re.compile(r"[A-Za-z][A-Za-z&'-]*")


def _words(text):
    return [w.lower() for w in WORD.findall(text)]


def _claim_holds(claim, c):
    kind, ids = claim.get("type"), sorted(claim.get("ids") or [])
    if kind == "leader":
        return ids == c["best_1d"]
    if kind == "laggard":
        return ids == c["worst_1d"]
    if kind == "biggest_mover":
        return ids == c["biggest_mover_1d"]
    if kind == "only_up":
        return ids == c["up"]
    if kind == "only_down":
        return ids == c["down"]
    if kind == "all_up":
        return c["all_up"]
    if kind == "all_down":
        return c["all_down"]
    if kind == "most_up":
        return len(c["up"]) >= 4
    if kind == "most_down":
        return len(c["down"]) >= 4
    if kind == "group_beat_spy":
        return c["group_beat_spy"]
    if kind == "group_trailed_spy":
        return c["group_trailed_spy"]
    return False


def _unknown_names(own_text):
    """Capitalised words (not starting a sentence) and ticker-like words that aren't known series."""
    found = []
    for sentence in re.split(r"(?<=[.!?;:])\s+|^", own_text):
        tokens = re.findall(r"[A-Za-z][A-Za-z&]*", sentence)
        for i, tok in enumerate(tokens):
            if tok in ALLOWED_NAMES:
                continue
            if tok.isupper() and len(tok) >= 2:
                found.append(tok)
            elif tok[0].isupper() and i > 0:
                found.append(tok)
    return found


def _unanchored_changes(text):
    """{T.change_*} placeholders don't name the stock, so the same sentence must already have
    named it (by name, ticker, or one of its own placeholders). Otherwise a true figure can
    read as another company's: "Apple fell 2.6% and fell 0.7%"."""
    found = []
    for sentence in re.split(r"(?<=[.!?;])\s+", text):
        for match in re.finditer(r"\{([A-Z]+)\.change_[a-z0-9]+\}", sentence):
            ticker = match.group(1)
            before = sentence[: match.start()]
            names = [ticker, NAMES.get(ticker, ticker)]
            named = f"{{{ticker}." in before or any(re.search(rf"\b{re.escape(n)}\b", before) for n in names)
            if not named:
                found.append(match.group(0))
    return found


def _check_text(label, text, claims, problems):
    unanchored = _unanchored_changes(text)
    if unanchored:
        problems.append(f"{label}: {unanchored} must follow the same company's name in the sentence")
    own = strip_placeholders(text)
    numbers = find_banned_numbers(own)
    if numbers:
        problems.append(f"{label}: numbers must come from placeholders, found {numbers}")
    words = set(_words(own))
    tagged_types = {cl.get("type") for cl in claims}
    backed = (UP_WORDS if tagged_types & UP_CLAIMS else set()) | (DOWN_WORDS if tagged_types & DOWN_CLAIMS else set())
    direction = sorted((words & DIRECTION) - backed)
    if direction:
        problems.append(f"{label}: direction words must come from placeholders, found {direction}")
    banned = sorted(words & BANNED)
    if banned:
        problems.append(f"{label}: advice, prediction or unsupported words {banned}")
    tagged = {cl.get("type") for cl in claims}
    for name, (triggers, needs) in NEEDS_TAG.items():
        hit = sorted(words & triggers)
        if hit and not tagged & needs:
            problems.append(f"{label}: {hit} needs a tagged {name} claim")
    unknown = _unknown_names(own)
    if unknown:
        problems.append(f"{label}: unknown names {unknown}")


def check(note, facts):
    problems = []
    if not isinstance(note, dict) or not isinstance(note.get("headline"), str):
        return ["note: missing headline"]
    bullets = note.get("bullets")
    if not isinstance(bullets, list) or len(bullets) != BULLETS:
        return [f"note: needs exactly {BULLETS} bullets"]
    for i, b in enumerate(bullets, 1):
        if not isinstance(b, dict) or not isinstance(b.get("text"), str) or not isinstance(b.get("claims", []), list):
            return [f"bullet {i}: malformed"]

    try:
        shown = render(note, facts)
    except UnknownFact as err:
        return [f"note: unknown placeholder {{{err}}}"]

    headline_claims = note.get("headline_claims", [])
    if not isinstance(headline_claims, list):
        return ["headline: malformed claims"]
    for claim in headline_claims:
        if claim.get("type") not in CLAIM_TYPES:
            problems.append(f"headline: unknown claim type {claim.get('type')!r}")
        elif not _claim_holds(claim, facts["claims"]):
            problems.append(f"headline: claim {claim} is false")
    _check_text("headline", note["headline"], headline_claims, problems)
    if len(shown["headline"]) > HEADLINE_MAX:
        problems.append(f"headline: {len(shown['headline'])} characters (max {HEADLINE_MAX})")
    for i, (b, text) in enumerate(zip(bullets, shown["bullets"]), 1):
        claims = b.get("claims", [])
        for claim in claims:
            if claim.get("type") not in CLAIM_TYPES:
                problems.append(f"bullet {i}: unknown claim type {claim.get('type')!r}")
            elif not _claim_holds(claim, facts["claims"]):
                problems.append(f"bullet {i}: claim {claim} is false")
        _check_text(f"bullet {i}", b["text"], claims, problems)
        if not placeholders(b["text"]):
            problems.append(f"bullet {i}: has no figures from the fact sheet")
        if len(text) > BULLET_MAX:
            problems.append(f"bullet {i}: {len(text)} characters (max {BULLET_MAX})")
    return problems
