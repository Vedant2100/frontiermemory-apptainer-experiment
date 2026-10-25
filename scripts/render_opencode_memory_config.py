#!/usr/bin/env python3
"""Render a shared OpenCode task prompt and Harbor config for either condition.

The prompt wrapper is byte-identical across conditions. A leaves the memory
slot empty; B fills only that slot with the frozen historical memory.
"""

from __future__ import annotations

import argparse
from pathlib import Path

import yaml


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-config", type=Path, required=True)
    parser.add_argument("--memory", type=Path)
    parser.add_argument("--prompt-template", type=Path, required=True)
    parser.add_argument("--output-config", type=Path, required=True)
    args = parser.parse_args()

    memory = args.memory.read_text(encoding="utf-8").strip() if args.memory else ""
    safe_memory = memory.replace("{{", "{ {").replace("}}", "} }")
    template = (
        "Work in the task repository at /app (the current working directory). "
        "Use repository-relative paths for reads and edits.\n\n"
        "The following reusable memory was distilled only from historical "
        "FrontierMemory trajectory evidence. Treat it as guidance, not as a "
        "specification; follow the current task's requirements.\n\n"
        "<historical_memory>\n"
        f"{safe_memory}\n"
        "</historical_memory>\n\n"
        "Current task instruction:\n{{ instruction }}\n"
    )
    args.prompt_template.parent.mkdir(parents=True, exist_ok=True)
    args.prompt_template.write_text(template, encoding="utf-8")

    config = yaml.safe_load(args.base_config.read_text(encoding="utf-8"))
    config["agents"][0]["kwargs"]["prompt_template_path"] = str(
        args.prompt_template.resolve()
    )
    args.output_config.parent.mkdir(parents=True, exist_ok=True)
    args.output_config.write_text(yaml.safe_dump(config, sort_keys=False), encoding="utf-8")
    condition = "B" if args.memory else "A"
    print(f"Wrote {condition} config: {args.output_config}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
