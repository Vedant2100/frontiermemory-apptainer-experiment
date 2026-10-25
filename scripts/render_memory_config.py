#!/usr/bin/env python3
"""Insert a locally available FrontierMemory artifact into the B config template."""
import argparse
from pathlib import Path
import textwrap


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--template", type=Path, default=Path("configs/mini-swe-ollama-7b-memory.template.yaml"))
    parser.add_argument("--memory", type=Path, required=True, help="Local MEMORY.md; do not publish gated-derived content")
    parser.add_argument("--output", type=Path, default=Path("configs/mini-swe-ollama-7b-memory.yaml"))
    args = parser.parse_args()
    template = args.template.read_text()
    memory = textwrap.indent(args.memory.read_text().strip(), "    ")
    marker = "    {{LOCAL_MEMORY}}"
    if template.count(marker) != 1:
        raise SystemExit(f"expected exactly one {marker!r} marker in {args.template}")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(template.replace(marker, memory) + "\n")
    print(f"Wrote local condition-B config to {args.output}")


if __name__ == "__main__":
    main()
