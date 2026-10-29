"""Fixed perturbation script for judge validation (preregistration v1, section 2.6).

Each perturbation makes a unit's claim false in a controlled way, so a judge should call it
`contradicted` when the unit's own cited evidence is shown. Four types:

- number:     the first number in the unit (outside citations and list markers) becomes n + 3.
- flag:       the first boolean-like word is swapped with its opposite (true<->false, yes<->no,
              enabled<->disabled, required<->optional, allowed<->forbidden, supported<->unsupported).
- identifier: the first backticked identifier is replaced by another backticked identifier from the
              same topic file. The replacement is chosen with the seeded RNG from the pool of
              identifiers in that file that do not occur in the unit.
- negation:   the first directive is negated: use -> do not use, always -> never,
              must -> must not, should -> should not (case is preserved).

All edits are position-exact on the original text. Citations are never touched.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from random import Random

from segment import CITATION, Unit

LIST_OR_HEADING = re.compile(r"^(\s*(?:#{1,6}\s+|[-*+]\s+|\d{1,9}[.)]\s+))")
NUMBER = re.compile(r"(?<![A-Za-z_0-9.])(\d+(?:\.\d+)?)(?![A-Za-z_0-9])")
FLAG_PAIRS = {
    "true": "false", "false": "true",
    "yes": "no", "no": "yes",
    "enabled": "disabled", "disabled": "enabled",
    "required": "optional", "optional": "required",
    "allowed": "forbidden", "forbidden": "allowed",
    "supported": "unsupported", "unsupported": "supported",
}
FLAG = re.compile(r"\b(" + "|".join(sorted(FLAG_PAIRS, key=len, reverse=True)) + r")\b", re.IGNORECASE)
NEGATIONS = {"use": "do not use", "always": "never", "must": "must not", "should": "should not"}
DIRECTIVE = re.compile(r"\b(" + "|".join(NEGATIONS) + r")\b", re.IGNORECASE)
IDENT = re.compile(r"`([A-Za-z_][\w./-]{2,})`")
TYPES = ("number", "flag", "identifier", "negation")


@dataclass(frozen=True)
class Perturbation:
    kind: str
    text: str  # perturbed unit text


def _masked(text: str) -> str:
    """Same-length copy with citations and the leading list or heading marker blanked out."""
    masked = CITATION.sub(lambda m: " " * len(m.group(0)), text)
    first_line_end = masked.find("\n")
    first = masked if first_line_end < 0 else masked[:first_line_end]
    marker = LIST_OR_HEADING.match(first)
    if marker:
        blank = " " * len(marker.group(1))
        masked = blank + masked[len(marker.group(1)):]
    return masked


def _replace_span(text: str, start: int, end: int, new: str) -> str:
    return text[:start] + new + text[end:]


def _number(unit: Unit) -> str | None:
    text = unit.text
    masked = _masked(text)
    match = NUMBER.search(masked)
    if not match:
        return None
    value = match.group(1)
    new = str(int(value) + 3) if "." not in value else f"{float(value) + 3:g}"
    if new == value:
        return None
    return _replace_span(text, match.start(), match.end(), new)


def _flag(unit: Unit) -> str | None:
    text = unit.text
    match = FLAG.search(_masked(text))
    if not match:
        return None
    word = text[match.start():match.end()]
    target = FLAG_PAIRS[word.lower()]
    if word.isupper():
        target = target.upper()
    elif word[0].isupper():
        target = target.capitalize()
    return _replace_span(text, match.start(), match.end(), target)


def _identifier(unit: Unit, pool: list[str], rng: Random) -> str | None:
    text = unit.text
    match = None
    for candidate in IDENT.finditer(_masked(text)):
        match = candidate
        break
    if match is None:
        return None
    old = match.group(1)
    options = sorted(name for name in pool if name != old and f"`{name}`" not in text)
    if not options:
        return None
    new = rng.choice(options)
    return _replace_span(text, match.start(), match.end(), new)


def _negation(unit: Unit) -> str | None:
    text = unit.text
    match = DIRECTIVE.search(_masked(text))
    if not match:
        return None
    word = text[match.start():match.end()]
    target = NEGATIONS[word.lower()]
    if word[0].isupper():
        target = target[0].upper() + target[1:]
    return _replace_span(text, match.start(), match.end(), target)


def file_identifier_pool(file_text: str) -> list[str]:
    """Backticked identifiers anywhere in the topic file (used for the identifier swap)."""
    return sorted({m.group(1) for m in IDENT.finditer(CITATION.sub(" ", file_text))})


def applicable(unit: Unit, pool: list[str], rng: Random) -> dict[str, str]:
    """Return {type: perturbed text} for each perturbation type that applies to the unit.

    The identifier swap uses the RNG, so pass the same RNG when you need reproducibility.
    """
    out: dict[str, str] = {}
    for kind, fn in (("number", lambda: _number(unit)),
                     ("flag", lambda: _flag(unit)),
                     ("identifier", lambda: _identifier(unit, pool, rng)),
                     ("negation", lambda: _negation(unit))):
        new = fn()
        if new is not None and new != unit.text:
            out[kind] = new
    return out


_TOKEN = re.compile(r"[A-Za-z0-9_.\-]+")


def changed_tokens(original: str, perturbed: str) -> list[str]:
    """Tokens of the original text that the perturbation removed or replaced."""
    from difflib import SequenceMatcher

    a = _TOKEN.findall(original)
    b = _TOKEN.findall(perturbed)
    out: list[str] = []
    for tag, i1, i2, _j1, _j2 in SequenceMatcher(a=a, b=b, autojunk=False).get_opcodes():
        if tag in ("replace", "delete"):
            out.extend(a[i1:i2])
    return [t.strip(".").lower() for t in out if t.strip(".")]


def detectable(original: str, perturbed: str, evidence_text: str) -> bool:
    """A1: at least one changed token occurs as a whole token in the evidence."""
    evidence_tokens = {t.lower().strip(".") for t in _TOKEN.findall(evidence_text)}
    return any(tok in evidence_tokens for tok in changed_tokens(original, perturbed))
