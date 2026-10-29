"""Deterministic markdown unit parser for memory topic files (preregistration v1, section 2.1).

A topic file is split into units: heading, bullet, numbered item, paragraph, or fenced code
block. Nested bullets are separate units. Each unit carries the citations
`inputs/tNNNN.json#step=K` found in its text.

Layout that is not a unit (blank lines, thematic breaks, and the outer ```markdown wrapper
that the generator put around most topic files) is kept verbatim as raw lines and is never
removed. The wrapper is detected when the first non-blank line opens a fence whose info
string is `markdown` or `md`. If the last non-blank line closes it, the wrapper is both lines.
If it is never closed (12 files), only the opener is raw. The content in between is
segmented normally.

Reassembly reproduces the input byte-for-byte when no unit is removed. When units are removed,
blank lines that would otherwise be doubled after a removed unit are dropped.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Iterable, Union

CITATION = re.compile(r"inputs/(t\d{4}\.jsonl?)#step=(\d+)")
HEADING = re.compile(r"^ {0,3}#{1,6}(?:[ \t]|$)")
FENCE = re.compile(r"^([ \t]*)(`{3,}|~{3,})(.*)$")
BULLET = re.compile(r"^([ \t]*)[-*+](?:[ \t]|$)")
NUMBERED = re.compile(r"^([ \t]*)\d{1,9}[.)](?:[ \t]|$)")
THEMATIC = re.compile(r"^ {0,3}([-*_])(?:[ \t]*\1){2,}[ \t]*$")
WRAPPER_INFO = {"markdown", "md"}

KINDS = ("heading", "bullet", "numbered", "paragraph", "code")


@dataclass
class Unit:
    """One governable unit. `uid` is 1-based within its file, in original order."""

    uid: int
    kind: str
    lines: list[str]
    citations: list[tuple[str, int]] = field(default_factory=list)
    code_nonblank: int = 0  # non-blank lines strictly inside a fenced code block

    @property
    def text(self) -> str:
        return "\n".join(self.lines)

    @property
    def governable(self) -> bool:
        """Headings are structural and never removed."""
        return self.kind != "heading"


Item = Union[Unit, str]


@dataclass
class Document:
    items: list[Item]
    trailing_newline: bool
    wrapped: bool

    def units(self) -> list[Unit]:
        return [item for item in self.items if isinstance(item, Unit)]


def _is_blank(line: str) -> bool:
    return line.strip() == ""


def _indent(line: str) -> int:
    return len(line) - len(line.lstrip(" \t"))


def _closes(line: str, char: str, length: int) -> bool:
    match = re.match(r"^[ \t]{0,3}(`{3,}|~{3,})[ \t]*$", line)
    return bool(match) and match.group(1)[0] == char and len(match.group(1)) >= length


def _is_list_item(line: str) -> bool:
    return bool(BULLET.match(line) or NUMBERED.match(line))


def _is_plain(line: str) -> bool:
    return not (
        _is_blank(line)
        or HEADING.match(line)
        or _is_list_item(line)
        or THEMATIC.match(line)
        or FENCE.match(line)
    )


def _fence_info_ok(match: re.Match) -> bool:
    marker, info = match.group(2), match.group(3)
    return not (marker[0] == "`" and "`" in info)


def _find_wrapper(lines: list[str]) -> tuple[int, int | None] | None:
    """Return (opener_index, closer_index or None) for a whole-file ```markdown wrapper.

    Some generated files open the wrapper but never close it. For those the opener is kept as
    a raw line and the rest of the file is segmented (closer is None).
    """
    nonblank = [i for i, line in enumerate(lines) if not _is_blank(line)]
    if not nonblank:
        return None
    first = nonblank[0]
    opener = FENCE.match(lines[first])
    if not opener or not _fence_info_ok(opener):
        return None
    if opener.group(3).strip().lower() not in WRAPPER_INFO:
        return None
    marker = opener.group(2)
    last = nonblank[-1]
    if last > first and _closes(lines[last], marker[0], len(marker)):
        return first, last
    return first, None


def _make_unit(uid: int, kind: str, lines: list[str], code_nonblank: int = 0) -> Unit:
    text = "\n".join(lines)
    return Unit(
        uid=uid,
        kind=kind,
        lines=lines,
        citations=[(name, int(step)) for name, step in CITATION.findall(text)],
        code_nonblank=code_nonblank,
    )


def parse(text: str) -> Document:
    """Split a topic file into units and raw layout lines."""
    if text == "":
        return Document(items=[], trailing_newline=False, wrapped=False)
    trailing = text.endswith("\n")
    body = text[:-1] if trailing else text
    lines = body.split("\n")

    wrapper = _find_wrapper(lines)
    items: list[Item] = []
    closer_idx: int | None = None
    start = 0
    if wrapper is not None:
        first, closer_idx = wrapper
        items.extend(lines[:first + 1])  # blank lines before the wrapper and the opener
        start = first + 1
    uid = 0

    def emit_raw(line: str) -> None:
        items.append(line)

    end = len(lines)
    i = start
    while i < end:
        line = lines[i]
        if closer_idx is not None and i == closer_idx:
            emit_raw(line)
            i += 1
            continue
        if _is_blank(line) or THEMATIC.match(line):
            emit_raw(line)
            i += 1
            continue
        fence = FENCE.match(line)
        if fence and _fence_info_ok(fence):
            marker = fence.group(2)
            j = i + 1
            while j < end and not _closes(lines[j], marker[0], len(marker)):
                j += 1
            closed = j < end
            block_end = j + 1 if closed else end
            inner = lines[i + 1:j] if closed else lines[i + 1:end]
            uid += 1
            items.append(_make_unit(uid, "code", lines[i:block_end],
                                    code_nonblank=sum(1 for x in inner if not _is_blank(x))))
            i = block_end
            continue
        if HEADING.match(line):
            uid += 1
            items.append(_make_unit(uid, "heading", [line]))
            i += 1
            continue
        bullet = BULLET.match(line)
        numbered = NUMBERED.match(line)
        if bullet or numbered:
            marker_indent = _indent(line)
            j = i + 1
            while j < end:
                nxt = lines[j]
                if _is_blank(nxt) or _is_list_item(nxt) or HEADING.match(nxt) or FENCE.match(nxt):
                    break
                if THEMATIC.match(nxt) or _indent(nxt) <= marker_indent:
                    break
                j += 1
            uid += 1
            items.append(_make_unit(uid, "bullet" if bullet else "numbered", lines[i:j]))
            i = j
            continue
        j = i + 1
        while j < end and _is_plain(lines[j]):
            j += 1
        uid += 1
        items.append(_make_unit(uid, "paragraph", lines[i:j]))
        i = j

    return Document(items=items, trailing_newline=trailing, wrapped=wrapper is not None)


def reassemble(doc: Document, keep: Iterable[int] | None = None) -> str:
    """Rebuild the file from kept units (by uid) in original order.

    keep=None keeps every unit, which reproduces the original text exactly. Raw lines are
    always kept. After a removed unit, a blank raw line is dropped when the previous emitted
    line is blank or there is none, so removal never leaves doubled blank lines.
    """
    keep_set = None if keep is None else set(keep)
    out: list[str] = []
    removed_pending = False
    for item in doc.items:
        if isinstance(item, Unit):
            if keep_set is None or item.uid in keep_set or not item.governable:
                out.extend(item.lines)
                removed_pending = False
            else:
                removed_pending = True
            continue
        if _is_blank(item) and removed_pending and (not out or _is_blank(out[-1])):
            continue
        out.append(item)
        if not _is_blank(item):
            removed_pending = False
    if removed_pending:
        while out and _is_blank(out[-1]):
            out.pop()
    body = "\n".join(out)
    if doc.trailing_newline:
        body += "\n"
    return body


def kept_text_is_headings_only(doc: Document, keep: Iterable[int]) -> bool:
    """True when no non-heading unit survives. Such a file is dropped by the governor."""
    keep_set = set(keep)
    return not any(u.governable and u.uid in keep_set for u in doc.units())
