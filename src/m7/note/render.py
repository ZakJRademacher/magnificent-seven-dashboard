"""Turn the writer's placeholders into text from the fact sheet.

The writer returns sentences such as "{NVDA.move_1d} and led the group." Each
{id} is replaced by that fact's text ("Nvidia rose 4.2%"), so every number and
every direction word on the page comes from code.
"""

import re

PLACEHOLDER = re.compile(r"\{([^{}]*)\}")


class UnknownFact(ValueError):
    """A placeholder names a fact that isn't in the fact sheet."""


def placeholders(text):
    return PLACEHOLDER.findall(text)


def strip_placeholders(text):
    """The writer's own words, with every placeholder removed."""
    return PLACEHOLDER.sub(" ", text)


def render_text(text, facts):
    def fill(match):
        fact_id = match.group(1)
        if fact_id not in facts["facts"]:
            raise UnknownFact(fact_id)
        return facts["facts"][fact_id]["text"]

    out = PLACEHOLDER.sub(fill, text)
    out = re.sub(r"\s+", " ", out).strip()
    return out[:1].upper() + out[1:]


def render(note, facts):
    """The note as it will be shown: {"as_of", "headline", "bullets": [str, str, str]}."""
    return {
        "as_of": facts["as_of"],
        "headline": render_text(note["headline"], facts),
        "bullets": [render_text(b["text"], facts) for b in note["bullets"]],
    }
