#!/usr/bin/env python3
"""Append a deterministic "Complete Topic List" to a memory folder's MEMORY.md.

Used for the M3 (memory/frozen-v5-fullindex) and R25 arms: the LLM-written index in v5 was
truncated at its output cap, so every topics/*.md file is listed mechanically with its title.
Titles are each file's first markdown heading (leading '#'s stripped), else the file stem.

Usage: complete_memory_index.py <memory_dir_in> <memory_dir_out>

Copies every file of <memory_dir_in> into <memory_dir_out> (which must not exist or be empty),
then rewrites MEMORY.md as original.rstrip('\\n') + '\\n' + appended lines + '\\n'. The input
folder is never modified. Standard library only.
"""

from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path


def topic_title(path: Path) -> str:
    text = path.read_text(encoding="utf-8")
    for line in text.splitlines():
        if line.startswith("#"):
            title = line.lstrip("#").strip()
            if title:
                return title
            break
    return path.stem


def completed_index(memory_dir: Path) -> str:
    original = (memory_dir / "MEMORY.md").read_text(encoding="utf-8")
    lines = [
        "",
        "## Complete Topic List",
        "",
        "Every topic file in `topics/`, with its title. (Appended mechanically; titles are each file's first heading.)",
        "",
    ]
    for path in sorted((memory_dir / "topics").glob("*.md")):
        lines.append(f"- topics/{path.name}: {topic_title(path)}")
    return original.rstrip("\n") + "\n" + "\n".join(lines) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("memory_dir_in", type=Path)
    parser.add_argument("memory_dir_out", type=Path)
    args = parser.parse_args()
    src, dst = args.memory_dir_in, args.memory_dir_out
    if not (src / "MEMORY.md").is_file() or not (src / "topics").is_dir():
        raise SystemExit(f"{src} must contain MEMORY.md and topics/")
    if dst.exists() and any(dst.iterdir()):
        raise SystemExit(f"{dst} exists and is not empty")
    dst.mkdir(parents=True, exist_ok=True)
    for path in sorted(src.rglob("*")):
        rel = path.relative_to(src)
        if path.is_dir():
            (dst / rel).mkdir(parents=True, exist_ok=True)
        elif path.is_file() and rel.as_posix() != "MEMORY.md":
            shutil.copy2(path, dst / rel)
    (dst / "MEMORY.md").write_text(completed_index(src), encoding="utf-8")
    print(f"wrote {dst / 'MEMORY.md'} ({(dst / 'MEMORY.md').stat().st_size} bytes), "
          f"{len(list((dst / 'topics').glob('*.md')))} topics listed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
