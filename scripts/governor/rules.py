"""Deterministic governor rules (preregistration v1, section 2.2 and the separation rule in 2.5).

R-artifact: a fenced code block with more than 12 non-blank lines inside its fences is removed.
This operationalizes the official ban on reproducing prior final artifacts.

Strict-rule predicate: an `insufficient` unit is dropped under the strict rule only if it
contains a concrete technical assertion, meaning any of:
  - a digit (after citations and the leading list or heading marker are removed);
  - a backticked identifier;
  - a command-like token.
"""

from __future__ import annotations

import re

from segment import CITATION, Unit

R_ARTIFACT_MAX_NONBLANK = 12

_LEADING_MARKER = re.compile(r"^\s*(?:#{1,6}\s+|[-*+]\s+|\d{1,9}[.)]\s+)")
_BACKTICKED = re.compile(r"`[^`\n]+`")
_COMMAND = re.compile(
    r"(?:^|\s)(?:\$\s|\./|/[\w.-]+/|--?[A-Za-z][\w-]*|"
    r"(?:python3?|pip3?|npm|npx|node|git|make|pytest|cargo|go|bash|sh|curl|docker|apptainer|"
    r"sed|awk|grep|find|cat|ls|cd|export|uv|conda|mkdir|chmod|rm|cp|mv|tar|wget|sbatch|"
    r"scontrol|squeue|ollama|apt|yum|dnf|pipx|poetry|mvn|gradle|javac|gcc|cmake)\s)"
)


def r_artifact(unit: Unit) -> bool:
    return unit.kind == "code" and unit.code_nonblank > R_ARTIFACT_MAX_NONBLANK


def concrete_technical_assertion(unit: Unit) -> bool:
    text = CITATION.sub(" ", unit.text)
    first = text.split("\n", 1)[0]
    text = text.replace(first, _LEADING_MARKER.sub("", first, count=1), 1)
    if re.search(r"\d", text):
        return True
    if _BACKTICKED.search(text):
        return True
    return bool(_COMMAND.search(text))
