#!/usr/bin/env python3
"""Condense the whole pinned joint-674-v1.0 corpus into step-numbered evidence (memory v5).

CPU-only and deterministic. Reads only data/corpus/joint-674-v1.0-pinned/inputs/ after
checking SHA256SUMS. Handles five trajectory layouts:

- ATIF JSON (object with a "steps" list): step id = ATIF step_id.
- OpenCode-style JSON (object with "info" and "messages"): step id = 1-based message index.
- Codex rollout JSONL, Claude Code JSONL, ACP JSONL: step id = 1-based JSONL line number.

Kept: user messages (the first is the task instruction), assistant messages, tool calls
with full arguments, observations (capped at 4,000 chars, head + tail), and the final
verifier result line. Dropped: reasoning and thinking content, developer/system prompts,
and bookkeeping records. Each trajectory is capped at 100,000 characters (head and tail
kept, the middle marked as truncated). Outputs contain corpus text and stay in a
git-ignored results directory.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from collections import Counter
from pathlib import Path

EXPECTED_MANIFEST_SHA256 = "c7d31214ed20af4f14f46c4b9a838ebc9aa35a9491dfbce0fa50f7aa456eedd1"
VERDICT = re.compile(r"Verifier result\s*[:\-]?\s*(PASS|FAIL)\b", re.IGNORECASE)
OBS_CAP, OBS_HALF = 4000, 2000
BLOCK_CAP, BLOCK_HALF = 24000, 12000
TRAJ_CAP = 100000
TAIL_SEARCH = 3  # the verifier line must be among the last items of a trajectory

# An item is (step_id, role, text). Items sharing a step id are rendered as one block.
Item = tuple[int, str, str]


def cap(text: str, limit: int, half: int) -> tuple[str, bool]:
    if len(text) <= limit:
        return text, False
    dropped = len(text) - 2 * half
    return text[:half] + f"\n...[middle omitted: {dropped} chars]...\n" + text[-half:], True


def text_of(value: object) -> str:
    """Flatten a content value (string, list of blocks, or dict) to text."""
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        parts = []
        for item in value:
            if isinstance(item, dict) and isinstance(item.get("text"), str):
                parts.append(item["text"])
            elif isinstance(item, dict) and isinstance(item.get("content"), (str, list, dict)):
                parts.append(text_of(item["content"]))
            elif isinstance(item, str):
                parts.append(item)
            else:
                parts.append(json.dumps(item, ensure_ascii=False, sort_keys=True))
        return "\n".join(p for p in parts if p)
    if isinstance(value, dict):
        if isinstance(value.get("text"), str):
            return value["text"]
        if isinstance(value.get("results"), list):
            return text_of([r.get("content") if isinstance(r, dict) else r for r in value["results"]])
        return json.dumps(value, ensure_ascii=False, sort_keys=True)
    return json.dumps(value, ensure_ascii=False)


class Stats:
    def __init__(self) -> None:
        self.observations_capped = 0
        self.blocks_capped = 0
        self.reasoning_dropped = 0


def render_call(name: str, args: object, stats: Stats) -> str:
    lines = [f"tool_call: {name}"]
    if isinstance(args, dict):
        for key, value in args.items():
            if isinstance(value, str):
                body, capped = cap(value, BLOCK_CAP, BLOCK_HALF)
                stats.blocks_capped += capped
                lines.append(f"  arg {key} (verbatim text):")
                lines.append(body)
            else:
                lines.append(f"  arg {key} (json): " + json.dumps(value, ensure_ascii=False, sort_keys=True))
    elif isinstance(args, str):
        body, capped = cap(args, BLOCK_CAP, BLOCK_HALF)
        stats.blocks_capped += capped
        lines.append("  arguments (verbatim text):")
        lines.append(body)
    elif args is not None:
        lines.append("  arguments (json): " + json.dumps(args, ensure_ascii=False, sort_keys=True))
    return "\n".join(lines)


def observation(text: str, stats: Stats) -> str:
    text = text.strip()
    body, capped = cap(text, OBS_CAP, OBS_HALF)
    stats.observations_capped += capped
    return "observation: " + body


def message(role: str, text: str, stats: Stats) -> str:
    body, capped = cap(text.strip(), BLOCK_CAP, BLOCK_HALF)
    stats.blocks_capped += capped
    return f"{role} message: {body}"


# ---------------------------------------------------------------- ATIF (JSON with steps)

def parse_atif(doc: dict, stats: Stats) -> list[Item]:
    items: list[Item] = []
    steps = doc.get("steps") or []
    ids = [int(s["step_id"]) for s in steps]
    if ids != list(range(1, len(steps) + 1)):
        raise ValueError("ATIF step ids are not 1..N")
    for step in steps:
        sid = int(step["step_id"])
        source = step.get("source")
        if step.get("reasoning_content"):
            stats.reasoning_dropped += 1
        if source == "system":
            continue
        text = str(step.get("message") or "")
        if text.strip():
            role = "user" if source == "user" else "assistant"
            items.append((sid, role, message(role, text, stats)))
        for call in step.get("tool_calls") or []:
            name = call.get("function_name") or call.get("name") or "?"
            items.append((sid, "assistant", render_call(name, call.get("arguments"), stats)))
        obs = text_of(step.get("observation"))
        if obs.strip():
            items.append((sid, "tool", observation(obs, stats)))
    return items


# ------------------------------------------------------ OpenCode-style (info + messages)

def parse_opencode(doc: dict, stats: Stats) -> list[Item]:
    items: list[Item] = []
    for index, msg in enumerate(doc.get("messages") or [], start=1):
        role = (msg.get("info") or {}).get("role", "assistant")
        role = "user" if role == "user" else "assistant"
        for part in msg.get("parts") or []:
            kind = part.get("type")
            if kind == "text" and str(part.get("text") or "").strip():
                items.append((index, role, message(role, str(part["text"]), stats)))
            elif kind == "tool":
                state = part.get("state") or {}
                items.append((index, "assistant", render_call(str(part.get("tool") or "?"), state.get("input"), stats)))
                output = text_of(state.get("output"))
                if output.strip():
                    items.append((index, "tool", observation(output, stats)))
            elif kind == "reasoning":
                stats.reasoning_dropped += 1
    return items


# ------------------------------------------------------------------ JSONL (per-line records)

def parse_jsonl(lines: list[dict], stats: Stats) -> list[Item]:
    items: list[Item] = []
    for number, rec in enumerate(lines, start=1):
        kind = rec.get("type")
        if kind == "response_item":  # Codex rollout
            payload = rec.get("payload") or {}
            ptype = payload.get("type")
            if ptype == "message":
                role = payload.get("role")
                if role in ("user", "assistant"):
                    items.append((number, role, message(role, text_of(payload.get("content")), stats)))
            elif ptype in ("function_call", "custom_tool_call"):
                args = payload.get("arguments", payload.get("input"))
                items.append((number, "assistant", render_call(str(payload.get("name") or "?"), args, stats)))
            elif ptype in ("function_call_output", "custom_tool_call_output"):
                output = text_of(payload.get("output"))
                if output.strip():
                    items.append((number, "tool", observation(output, stats)))
            elif ptype == "reasoning":
                stats.reasoning_dropped += 1
        elif kind == "user" and isinstance(rec.get("message"), dict):  # Claude Code
            content = rec["message"].get("content")
            if isinstance(content, str):
                items.append((number, "user", message("user", content, stats)))
            elif isinstance(content, list):
                for block in content:
                    if not isinstance(block, dict):
                        continue
                    if block.get("type") == "tool_result":
                        output = text_of(block.get("content"))
                        if output.strip():
                            items.append((number, "tool", observation(output, stats)))
                    elif block.get("type") == "text":
                        items.append((number, "user", message("user", str(block.get("text") or ""), stats)))
        elif kind == "assistant" and isinstance(rec.get("message"), dict):  # Claude Code
            for block in rec["message"].get("content") or []:
                if not isinstance(block, dict):
                    continue
                if block.get("type") == "text":
                    items.append((number, "assistant", message("assistant", str(block.get("text") or ""), stats)))
                elif block.get("type") == "tool_use":
                    items.append((number, "assistant", render_call(str(block.get("name") or "?"), block.get("input"), stats)))
                elif block.get("type") == "thinking":
                    stats.reasoning_dropped += 1
        elif kind == "user_message":  # ACP
            items.append((number, "user", message("user", str(rec.get("text") or ""), stats)))
        elif kind == "agent_message":  # ACP
            items.append((number, "assistant", message("assistant", str(rec.get("text") or ""), stats)))
        elif kind == "agent_thought":  # ACP
            stats.reasoning_dropped += 1
        elif kind == "tool_call":  # ACP
            title = str(rec.get("title") or "?")
            head = f"tool_call: {title}\n  kind: {rec.get('kind')}\n  status: {rec.get('status')}"
            outputs: list[str] = []
            diffs: list[str] = []
            for entry in rec.get("content") or []:
                if not isinstance(entry, dict):
                    continue
                if entry.get("type") == "diff":
                    diffs.append(f"  path: {entry.get('path')}\n  old (verbatim):\n{entry.get('oldText') or ''}\n  new (verbatim):\n{entry.get('newText') or ''}")
                else:
                    inner = entry.get("content")
                    text = inner.get("text") if isinstance(inner, dict) else None
                    if isinstance(text, str) and text.strip():
                        outputs.append(text)
            if diffs:
                body, capped = cap("\n".join(diffs), BLOCK_CAP, BLOCK_HALF)
                stats.blocks_capped += capped
                head += "\n" + body
            items.append((number, "assistant", head))
            if outputs:
                items.append((number, "tool", observation("\n".join(outputs), stats)))
    return items


# ---------------------------------------------------------------- rendering and capping

def build_text(file_name: str, fmt: str, items: list[Item], outcome: str) -> tuple[str, dict]:
    blocks: list[str] = []
    block_steps: list[int] = []
    grouped: list[tuple[int, str, list[str]]] = []
    for sid, role, text in items:
        if grouped and grouped[-1][0] == sid:
            grouped[-1][2].append(text)
        else:
            grouped.append((sid, role, [text]))
    for sid, role, texts in grouped:
        blocks.append(f"--- step={sid} role={role}\n" + "\n".join(texts))
        block_steps.append(sid)

    header = (
        f"FILE: inputs/{file_name}\n"
        f"FORMAT: {fmt}\n"
        f"RECORDED OUTCOME: {outcome}\n"
        f"TOTAL STEPS: {len(block_steps)}\n"
        "STEPS:\n"
    )
    full = header + "\n".join(blocks) + "\n"
    omitted: list[int] = []
    truncated = False
    if len(full) > TRAJ_CAP:
        truncated = True
        marker_budget = 300
        budget = TRAJ_CAP - len(header) - marker_budget
        head_budget = budget // 2
        used = 0
        head_count = 0
        for block in blocks:
            if used + len(block) + 1 > head_budget:
                break
            used += len(block) + 1
            head_count += 1
        tail_idx: list[int] = []
        tail_used = 0
        for index in range(len(blocks) - 1, head_count - 1, -1):
            if used + tail_used + len(blocks[index]) + 1 > budget:
                break
            tail_idx.append(index)
            tail_used += len(blocks[index]) + 1
        tail_idx.reverse()
        kept = set(range(head_count)) | set(tail_idx)
        omitted = [block_steps[i] for i in range(len(blocks)) if i not in kept]
        parts: list[str] = []
        previous_kept = True
        for index, block in enumerate(blocks):
            if index in kept:
                if not previous_kept and omitted:
                    parts.append(
                        f"[TRUNCATED: steps {omitted[0]}-{omitted[-1]} omitted "
                        f"({len(omitted)} steps) to fit the {TRAJ_CAP}-char trajectory cap]"
                    )
                parts.append(block)
                previous_kept = True
            else:
                previous_kept = False
        text = header + "\n".join(parts) + "\n"
    else:
        text = full
    if len(text) > TRAJ_CAP:
        raise ValueError(f"{file_name}: evidence {len(text)} chars exceeds the cap")
    return text, {
        "trajectory_steps_in_evidence": len(block_steps) - len(omitted),
        "omitted_steps": omitted,
        "truncated": truncated,
        "uncapped_chars": len(full),
        "evidence_chars": len(text),
        "step_ids": block_steps,
    }


def outcome_of(items: list[Item]) -> str | None:
    """Return PASS or FAIL from the verifier line near the end of the trajectory."""
    for sid, role, text in reversed(items[-TAIL_SEARCH:]):
        match = VERDICT.search(text)
        if match:
            return match.group(1).upper()
    return None


def load_items(path: Path, stats: Stats) -> tuple[str, list[Item]]:
    if path.suffix == ".jsonl":
        lines = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
        codex = any(rec.get("type") == "session_meta" for rec in lines)
        return ("codex-rollout" if codex else "jsonl-claude-or-acp"), parse_jsonl(lines, stats)
    doc = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(doc, dict) and isinstance(doc.get("steps"), list):
        return "atif-json", parse_atif(doc, stats)
    if isinstance(doc, dict) and isinstance(doc.get("messages"), list):
        return "opencode-json", parse_opencode(doc, stats)
    raise ValueError(f"{path.name}: unrecognized layout")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--corpus", type=Path, required=True)
    parser.add_argument("--out-dir", type=Path, required=True)
    args = parser.parse_args()

    manifest_bytes = (args.corpus / "SHA256SUMS").read_bytes()
    if hashlib.sha256(manifest_bytes).hexdigest() != EXPECTED_MANIFEST_SHA256:
        raise SystemExit("Unexpected corpus manifest SHA-256")
    checksums: dict[str, str] = {}
    for line in manifest_bytes.decode("utf-8").splitlines():
        digest, relative = line.strip().split(maxsplit=1)
        checksums[relative.lstrip("*")] = digest

    inputs = sorted((args.corpus / "inputs").iterdir(), key=lambda p: p.name)
    stems = [p.stem for p in inputs]
    if len(set(stems)) != len(stems):
        raise SystemExit("Duplicate trajectory stems")

    evidence_dir = args.out_dir / "evidence"
    evidence_dir.mkdir(parents=True, exist_ok=True)
    files: list[dict] = []
    formats: Counter = Counter()
    outcomes: Counter = Counter()
    totals = Counter()
    for path in inputs:
        relative = f"inputs/{path.name}"
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        if checksums.get(relative) != digest:
            raise SystemExit(f"Checksum mismatch against SHA256SUMS: {relative}")
        stats = Stats()
        fmt, items = load_items(path, stats)
        outcome = outcome_of(items)
        if outcome is None:
            raise SystemExit(f"{path.name}: no verifier result line near the end")
        text, meta = build_text(path.name, fmt, items, outcome)
        (evidence_dir / f"{path.stem}.txt").write_text(text, encoding="utf-8")
        formats[fmt] += 1
        outcomes[outcome] += 1
        totals["evidence_chars"] += meta["evidence_chars"]
        totals["uncapped_chars"] += meta["uncapped_chars"]
        totals["trajectories_truncated"] += int(meta["truncated"])
        totals["observations_capped"] += stats.observations_capped
        totals["blocks_capped"] += stats.blocks_capped
        totals["reasoning_items_dropped"] += stats.reasoning_dropped
        files.append({
            "id": path.stem,
            "file": relative,
            "sha256": digest,
            "format": fmt,
            "outcome": outcome,
            "evidence_file": f"evidence/{path.stem}.txt",
            "step_ids": meta["step_ids"],
            "omitted_steps": meta["omitted_steps"],
            "truncated": meta["truncated"],
            "evidence_chars": meta["evidence_chars"],
            "uncapped_chars": meta["uncapped_chars"],
            "observations_capped": stats.observations_capped,
            "blocks_capped": stats.blocks_capped,
            "reasoning_items_dropped": stats.reasoning_dropped,
        })

    index = {
        "corpus_manifest_sha256": EXPECTED_MANIFEST_SHA256,
        "caps": {
            "observation_cap_chars": OBS_CAP,
            "block_cap_chars": BLOCK_CAP,
            "trajectory_cap_chars": TRAJ_CAP,
        },
        "files": files,
    }
    (args.out_dir / "evidence-index.json").write_text(json.dumps(index, indent=2) + "\n", encoding="utf-8")
    summary = {
        "files": len(files),
        "formats": dict(formats),
        "outcomes": dict(outcomes),
        "trajectories_truncated": totals["trajectories_truncated"],
        "observations_capped": totals["observations_capped"],
        "blocks_capped": totals["blocks_capped"],
        "reasoning_items_dropped": totals["reasoning_items_dropped"],
        "total_evidence_chars": totals["evidence_chars"],
        "total_uncapped_chars": totals["uncapped_chars"],
        "max_evidence_chars": max(f["evidence_chars"] for f in files),
    }
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
