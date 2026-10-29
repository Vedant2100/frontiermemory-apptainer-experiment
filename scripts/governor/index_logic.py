"""Complete memory index, rebuilt the way memory/frozen-v5-fullindex was built.

scripts/complete_memory_index.py did not exist when this was written, so this module
implements the logic that M3 shows (verified byte-for-byte against M3's MEMORY.md, see the
test in test_governor.py):

1. The index body is the LLM-written index from memory v5, which is everything before the
   line "## Complete Topic List".
2. The "## Complete Topic List" section is appended mechanically. It lists every topic file
   in topics/ in sorted filename order as "- topics/<name>: <title>", where the title is the
   text of the file's first markdown heading, with the leading #s removed.

For a governed memory, the body is filtered: a body line that names a topic file no longer
in topics/ is removed. For M3 this removes nothing (checked by the test). The list is then
rebuilt from the topics that remain.
"""

from __future__ import annotations

import re
from pathlib import Path

from segment import HEADING

SECTION = "## Complete Topic List"
SECTION_INTRO = (
    "Every topic file in `topics/`, with its title. "
    "(Appended mechanically; titles are each file's first heading.)"
)
TOPIC_NAME = re.compile(r"\bg\d{3}-[A-Za-z0-9._-]+\.md\b")


def title_of(text: str) -> str:
    for line in text.split("\n"):
        if HEADING.match(line):
            return re.sub(r"^ {0,3}#{1,6}[ \t]*", "", line).rstrip()
    raise ValueError("topic file has no heading")


def split_index(index_text: str) -> tuple[list[str], list[str]]:
    """Return (body lines, appended-section lines), with the section marker excluded from body."""
    lines = index_text.split("\n")
    if SECTION not in lines:
        return lines, []
    pos = lines.index(SECTION)
    return lines[:pos], lines[pos:]


def filter_body(body: list[str], kept_names: set[str]) -> list[str]:
    out = []
    for line in body:
        names = TOPIC_NAME.findall(line)
        if any(name not in kept_names for name in names):
            continue
        out.append(line)
    return out


def build_complete_index(body: list[str], topics: dict[str, str]) -> str:
    """body: lines before the section. topics: {filename: file text}, any order."""
    names = sorted(topics)
    section = [SECTION, "", SECTION_INTRO, ""]
    section += [f"- topics/{name}: {title_of(topics[name])}" for name in names]
    lines = body + section
    return "\n".join(lines) + "\n"


def regenerate(source_index: Path, topics_dir: Path, kept_files: list[str]) -> str:
    """Build the complete index for a governed memory from the M3 index and the kept topic files."""
    body, _ = split_index(source_index.read_text(encoding="utf-8"))
    topics = {name: (topics_dir / name).read_text(encoding="utf-8") for name in kept_files}
    return build_complete_index(filter_body(body, set(kept_files)), topics)
