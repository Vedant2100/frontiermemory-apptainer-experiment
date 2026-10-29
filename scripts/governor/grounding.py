"""Deterministic grounding rule (preregistration v1, amendment A2).

Concrete tokens of a technical unit:
  - backticked spans, compared case-sensitively (the text between the backticks);
  - standalone numbers (integers or decimals) that are not part of a larger identifier, path, or
    version-like token, not part of citation markup (inputs/tNNNN.json#step=K), and not a step index
    ("step 4", "step=4"), and not a leading list or heading marker.

A unit is grounded when every concrete token occurs in its evidence. The evidence is the text of the
excerpts the judge would see (cited steps, or the top-3 BM25 steps), truncated to 2,000 characters
per step as in section 2.3. A backticked span matches as a substring of the evidence. A number
matches as a numeric token of the evidence. A unit with no concrete tokens is grounded
(vacuously); the validation report counts those units.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from segment import CITATION, Unit

BACKTICKED = re.compile(r"`([^`\n]+)`")
STEP_INDEX = re.compile(r"\bstep\s*=?\s*\d+\b", re.IGNORECASE)
LEADING_MARKER = re.compile(r"^(\s*(?:#{1,6}\s+|[-*+]\s+|\d{1,9}[.)]\s+))")
NUMBER = re.compile(r"(?<![A-Za-z0-9_.\-/#])(\d+(?:\.\d+)?)(?![A-Za-z0-9_\-/])")


@dataclass(frozen=True)
class ConcreteTokens:
    backticked: tuple[str, ...]
    numbers: tuple[str, ...]

    @property
    def count(self) -> int:
        return len(self.backticked) + len(self.numbers)


def _scrub(text: str) -> str:
    """Remove citation markup, step indices, and the leading list or heading marker of the first line."""
    text = CITATION.sub(" ", text)
    text = STEP_INDEX.sub(" ", text)
    first, sep, rest = text.partition("\n")
    first = LEADING_MARKER.sub(" ", first, count=1)
    return first + sep + rest


def concrete_tokens(unit_text: str) -> ConcreteTokens:
    scrubbed = _scrub(unit_text)
    backticked = tuple(m.group(1) for m in BACKTICKED.finditer(scrubbed) if m.group(1).strip())
    # Numbers inside backticks are part of the backticked token, not standalone numbers.
    outside = BACKTICKED.sub(" ", scrubbed)
    numbers = tuple(m.group(1) for m in NUMBER.finditer(outside))
    return ConcreteTokens(backticked=backticked, numbers=numbers)


def evidence_numbers(evidence_text: str) -> set[str]:
    return {m.group(1) for m in NUMBER.finditer(evidence_text)}


def grounding(unit: Unit, excerpt_texts: list[str]) -> tuple[bool, int]:
    """Return (grounded, number of concrete tokens that are missing from the evidence)."""
    tokens = concrete_tokens(unit.text)
    evidence = "\n".join(excerpt_texts)
    numbers_in_evidence = evidence_numbers(evidence)
    missing = 0
    for span in tokens.backticked:
        if span not in evidence:
            missing += 1
    for number in tokens.numbers:
        if number not in numbers_in_evidence:
            missing += 1
    return missing == 0, missing
