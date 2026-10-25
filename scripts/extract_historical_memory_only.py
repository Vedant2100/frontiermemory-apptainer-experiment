#!/usr/bin/env python3
"""Copy only the historical evidence-backed memories section for synthesis."""

from __future__ import annotations

import argparse
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    source = args.source.read_text(encoding="utf-8")
    marker = "## Memories\n"
    if marker not in source:
        raise ValueError("Historical source does not contain a Memories section")
    evidence_only = marker + source.split(marker, 1)[1].strip() + "\n"
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(evidence_only, encoding="utf-8")
    print(f"Extracted historical memory evidence to {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
