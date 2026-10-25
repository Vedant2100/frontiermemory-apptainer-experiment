#!/usr/bin/env python3
"""Ask the local Ollama model for evidence-linked memory from the corpus digest."""

from __future__ import annotations

import argparse
import hashlib
import json
import time
from pathlib import Path
from urllib.request import Request, urlopen


COMMANDS = ("pwd", "git", "cat", "sed", "grep", "nl", "python3", "pytest")
HEADINGS = (
    "Scope and Limits",
    "Repository Orientation",
    "Reading and Finding Code",
    "Choosing Project Tools",
    "Validation",
)
SYSTEM_PROMPT = """You turn evidence from FrontierMemory historical coding-agent trajectories into concise, reusable memory for a future coding agent.

The user message supplies eight exact command-family counts from 100 Mini-SWE-Agent histories, all with PASS markers. Counts show prevalence, not causation. File names are opaque and task identities are unavailable. Do not infer task diversity, causal effects, project conventions, exact command behavior, flags, subcommands, or utilities outside the supplied list. In particular, do not invent git subcommands.

Return one JSON object with exactly one key practices. It must be a list of exactly eight objects, one per supplied command, with no duplicates or omissions. Each object has exactly command and rule string fields. Keep each rule to one sentence, describe only a conventional use of that command family, and do not include any other command, utility, flag, or subcommand. Do not mention the withheld evaluation task."""


def parse_command_counts(summary: str) -> dict[str, int]:
    """Read required command prevalence values from the generated digest."""
    import re

    counts = {
        command: int(histories)
        for command, histories in re.findall(r"\x60([^\x60]+)\x60 \((\d+)/100 histories;", summary)
        if command in COMMANDS
    }
    missing = set(COMMANDS) - counts.keys()
    if missing:
        raise ValueError(f"Missing Mini-SWE command counts in digest: {sorted(missing)}")
    return counts


def render_memory(data: dict, counts: dict[str, int]) -> str:
    """Validate the constrained model response and render compact Markdown."""
    practices = data.get("practices")
    if not isinstance(practices, list):
        raise ValueError("Model response did not contain a practices list")
    commands = [item.get("command") for item in practices]
    if len(practices) != len(COMMANDS) or sorted(commands) != sorted(COMMANDS):
        raise ValueError("Model response must contain exactly one practice per observed command")
    lines = [
        "# Coding Workflow Memory",
        "",
        "This memory summarizes the official FrontierMemory v1.0 corpus. It uses command-family frequencies from 100 Mini-SWE-Agent histories; all 100 had PASS markers. These counts describe prevalence only and do not show which actions caused success. The corpus provides no mapping from opaque trajectory files to tasks.",
    ]
    groups = {
        "Repository Orientation": ("pwd", "git"),
        "Finding Relevant Code": ("grep", "cat"),
        "Inspecting Source": ("sed", "nl"),
        "Project Tools and Validation": ("python3", "pytest"),
    }
    by_command = {item["command"]: item for item in practices}
    for heading, group in groups.items():
        lines.extend(["", f"## {heading}"])
        for command in group:
            rule = by_command[command].get("rule")
            if not isinstance(rule, str) or not rule.strip():
                raise ValueError(f"Empty memory practice for {command}")
            lines.append(f"- **{command}:** {rule.strip()} (observed in {counts[command]}/100 histories).")
    return "\n".join(lines) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("summary", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("metrics", type=Path)
    parser.add_argument("--endpoint", default="http://127.0.0.1:11434/api/chat")
    parser.add_argument("--model", default="qwen2.5-coder:7b")
    args = parser.parse_args()

    summary = args.summary.read_text(encoding="utf-8")
    counts = parse_command_counts(summary)
    user_prompt = (
        "Create one practice for each observed command. Use only these exact counts:\n"
        + "\n".join(f"- {command}: {counts[command]}/100 histories" for command in COMMANDS)
        + "\n\nAll 100 histories have PASS markers. The full corpus has 674 opaque records."
    )
    request_data = {
        "model": args.model,
        "stream": False,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt},
        ],
        "options": {"temperature": 0, "num_ctx": 8192, "num_predict": 1400},
        "format": "json",
    }
    request_body = json.dumps(request_data).encode("utf-8")
    request = Request(args.endpoint, data=request_body, headers={"Content-Type": "application/json"})
    started = time.time()
    with urlopen(request, timeout=900) as response:
        result = json.load(response)
    elapsed = time.time() - started
    raw_content = result["message"]["content"].strip()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    try:
        content = render_memory(json.loads(raw_content), counts)
    except (json.JSONDecodeError, TypeError, KeyError) as error:
        raise RuntimeError("Ollama did not return the required structured memory") from error

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.metrics.parent.mkdir(parents=True, exist_ok=True)
    args.metrics.with_name("model-response.json").write_text(raw_content + "\n", encoding="utf-8")
    args.output.write_text(content + "\n", encoding="utf-8")
    args.metrics.write_text(
        json.dumps(
            {
                "model": args.model,
                "endpoint": args.endpoint,
                "temperature": 0,
                "num_ctx": 8192,
                "summary_sha256": hashlib.sha256(summary.encode("utf-8")).hexdigest(),
                "evidence_counts": counts,
                "raw_model_response": raw_content,
                "prompt_tokens": result.get("prompt_eval_count"),
                "completion_tokens": result.get("eval_count"),
                "ollama_total_duration_ns": result.get("total_duration"),
                "wall_seconds": round(elapsed, 3),
                "memory_bytes": len((content + "\n").encode("utf-8")),
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    print(f"Wrote {args.output} ({len(content.encode('utf-8'))} bytes) in {elapsed:.1f}s")


if __name__ == "__main__":
    main()
