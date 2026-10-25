#!/usr/bin/env python3
"""Create a compact, content-safe index of FrontierMemory v1.0 trajectories."""

from __future__ import annotations

import argparse
import json
import re
import shlex
from collections import Counter
from pathlib import Path
from typing import Any


CORPUS_NAME = "joint-674-v1.0"
CORPUS_SHA256 = "c7d31214ed20af4f14f46c4b9a838ebc9aa35a9491dfbce0fa50f7aa456eedd1"
SKIP_PREFIXES = {"env", "sudo", "timeout", "command", "builtin"}
ASSIGNMENT = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*=")
SHELL_TOOLS = {"bash", "bash_command", "Bash", "run_shell_command", "exec_command", "shell", "terminal"}
EXECUTABLE = re.compile(r"^[A-Za-z0-9_.+-]+$")
SHELL_CONTROL = {"if", "then", "else", "elif", "fi", "for", "while", "do", "done", "case", "esac"}


def command_root(command: Any) -> str | None:
    """Return only the first executable token, never command arguments."""
    if not isinstance(command, str) or not command.strip():
        return None
    first_segment = re.split(r"[;&|]", command, maxsplit=1)[0].strip()
    try:
        words = shlex.split(first_segment)
    except ValueError:
        words = first_segment.split()
    while words and (ASSIGNMENT.match(words[0]) or words[0] in SKIP_PREFIXES):
        words.pop(0)
    if not words:
        return None
    root = Path(words[0]).name
    return root if EXECUTABLE.fullmatch(root) and root not in SHELL_CONTROL and not root.startswith("-") else None


def command_from(arguments: Any) -> str | None:
    """Read a shell command from known tool-argument shapes."""
    if isinstance(arguments, str):
        try:
            value = json.loads(arguments)
        except json.JSONDecodeError:
            return arguments
        return command_from(value)
    if not isinstance(arguments, dict):
        return None
    for key in ("command", "cmd", "script", "keystrokes", "input_text"):
        value = arguments.get(key)
        if isinstance(value, str):
            return value
    return None


def add_call(summary: dict[str, Any], name: Any, arguments: Any) -> None:
    tool_name = str(name or "unknown")
    summary["tools"][tool_name] += 1
    if tool_name not in SHELL_TOOLS:
        return
    root = command_root(command_from(arguments))
    if root:
        summary["commands"][root] += 1
        summary["command_sequence"].append(root)


def summarize_atif(path: Path) -> dict[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8"))
    agent = data.get("agent") or {}
    summary: dict[str, Any] = {
        "file": path.name,
        "format": "ATIF JSON",
        "agent": agent.get("name", "unknown"),
        "model": agent.get("model_name", "unknown"),
        "steps": len(data.get("steps") or []),
        "tokens_in": 0,
        "tokens_out": 0,
        "tools": Counter(),
        "commands": Counter(),
        "command_sequence": [],
    }
    metrics = data.get("final_metrics") or {}
    summary["tokens_in"] = int(metrics.get("total_prompt_tokens") or 0)
    summary["tokens_out"] = int(metrics.get("total_completion_tokens") or 0)
    tail_messages = "\n".join(str(step.get("message") or "") for step in (data.get("steps") or [])[-3:])
    verifier_match = re.search(r"# Verifier result\s*(PASS|FAIL)", tail_messages, re.IGNORECASE)
    summary["verifier_result"] = verifier_match.group(1).upper() if verifier_match else "unknown"
    for step in data.get("steps") or []:
        for call in step.get("tool_calls") or []:
            add_call(summary, call.get("function_name"), call.get("arguments"))
    return summary


def summarize_jsonl(path: Path) -> dict[str, Any]:
    record_types: Counter[str] = Counter()
    item_types: Counter[str] = Counter()
    tools: Counter[str] = Counter()
    commands: Counter[str] = Counter()
    command_sequence: list[str] = []
    input_tokens = output_tokens = 0
    with path.open(encoding="utf-8") as stream:
        for line in stream:
            try:
                record = json.loads(line)
            except json.JSONDecodeError:
                continue
            if not isinstance(record, dict):
                continue
            record_type = str(record.get("type", "unknown"))
            record_types[record_type] += 1
            payload = record.get("payload")
            if not isinstance(payload, dict):
                continue
            if record_type == "response_item":
                item_type = str(payload.get("type", "unknown"))
                item_types[item_type] += 1
                if item_type == "custom_tool_call":
                    call_summary = {
                        "tools": tools,
                        "commands": commands,
                        "command_sequence": command_sequence,
                    }
                    add_call(call_summary, payload.get("name"), payload.get("input"))
            if record_type == "token_usage_record":
                usage = payload.get("usage") or {}
                input_tokens += int(usage.get("input_tokens") or 0)
                output_tokens += int(usage.get("output_tokens") or 0)
    return {
        "file": path.name,
        "format": "JSONL event stream",
        "agent": "event stream",
        "model": "recorded in event metadata",
        "steps": item_types.get("custom_tool_call", 0),
        "tokens_in": input_tokens,
        "tokens_out": output_tokens,
        "tools": tools,
        "commands": commands,
        "command_sequence": command_sequence,
        "verifier_result": "unknown",
        "record_types": record_types,
        "item_types": item_types,
    }


def summarize_file(path: Path) -> dict[str, Any]:
    if path.suffix == ".jsonl":
        return summarize_jsonl(path)
    return summarize_atif(path)


def format_counter(counter: Counter[str], limit: int = 10) -> str:
    if not counter:
        return "none recorded"
    pairs = counter.most_common(limit)
    return ", ".join(f"`{name}` ({count})" for name, count in pairs)


def write_report(files: list[Path], summaries: list[dict[str, Any]], output: Path) -> None:
    formats = Counter(item["format"] for item in summaries)
    agents = Counter(item["agent"] for item in summaries)
    models = Counter(item["model"] for item in summaries if item["model"] != "unknown")
    tools: Counter[str] = Counter()
    commands: Counter[str] = Counter()
    total_steps = total_input = total_output = 0
    for item in summaries:
        tools.update(item["tools"])
        commands.update(item["commands"])
        total_steps += item["steps"]
        total_input += item["tokens_in"]
        total_output += item["tokens_out"]

    mini_swe = [item for item in summaries if item["agent"] == "mini-swe-agent"]
    mini_status = Counter(item["verifier_result"] for item in mini_swe)
    mini_command_occurrences: Counter[str] = Counter()
    mini_command_files: Counter[str] = Counter()
    for item in mini_swe:
        mini_command_occurrences.update(item["commands"])
        mini_command_files.update(item["commands"].keys())

    lines = [
        "# Compact index of official FrontierMemory v1.0 trajectories",
        "",
        "This file contains aggregate metadata and command families only; it does not copy trajectory text, patches, or task answers.",
        "",
        "## Corpus coverage",
        f"- Corpus: `{CORPUS_NAME}`, validated digest `{CORPUS_SHA256}`.",
        f"- Files: {len(files)}; total source bytes: {sum(path.stat().st_size for path in files):,}.",
        f"- Formats: {format_counter(formats)}.",
        f"- Recorded agent labels: {format_counter(agents, 8)}.",
        f"- Recorded model labels: {format_counter(models, 8)}.",
        "",
        "## Aggregate activity",
        f"- Structured steps/tool actions counted: {total_steps:,}.",
        f"- Tokens recorded by source trajectories: {total_input:,} input and {total_output:,} output.",
        f"- Tool names: {format_counter(tools, 12)}.",
        f"- First shell-command tokens (arguments intentionally omitted): {format_counter(commands, 16)}.",
        "",
        "## Mini-SWE-Agent subset",
        f"- Histories: {len(mini_swe)}; final verifier markers: {format_counter(mini_status)}.",
        "- Command-root frequencies show what occurred, not what caused a pass.",
        "- Command families present in at least 5 histories: "
        + (", ".join(
            f"`{name}` ({mini_command_files[name]}/{len(mini_swe)} histories; {count} occurrences)"
            for name, count in mini_command_occurrences.most_common()
            if mini_command_files[name] >= 5
        ) or "none recorded")
        + ".",
        "",
        "## Deterministic cross-section",
        "Ten evenly spaced files are shown as compact records. Counts describe each file; command arguments and conversation text are omitted.",
    ]
    if summaries:
        indices = sorted({round(i * (len(summaries) - 1) / 9) for i in range(10)})
        for index in indices:
            item = summaries[index]
            commands_text = format_counter(item["commands"], 7)
            lines.append(
            f"- `{item['file']}`: {item['format']}; agent `{item['agent']}`; "
            f"model `{item['model']}`; {item['steps']} steps/tool actions; "
            f"{item['tokens_in']:,}/{item['tokens_out']:,} recorded input/output tokens; "
            f"command families: {commands_text}; first 8 shell executable tokens in order: "
            f"{', '.join(f'`{root}`' for root in item['command_sequence'][:8]) or 'none recorded'}."
        )
    lines.extend(
        [
            "",
            "## Use limits",
            "These aggregates support broad procedural observations only. Do not infer a project convention or task outcome from command counts alone; check representative trajectories when making a specific claim.",
            "",
        ]
    )
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text("\n".join(lines), encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("corpus", type=Path, help="directory containing JSON/JSONL trajectory files")
    parser.add_argument("output", type=Path, help="path for the compact Markdown index")
    args = parser.parse_args()
    files = sorted(path for path in args.corpus.iterdir() if path.suffix in {".json", ".jsonl"})
    summaries = [summarize_file(path) for path in files]
    write_report(files, summaries, args.output)


if __name__ == "__main__":
    main()
