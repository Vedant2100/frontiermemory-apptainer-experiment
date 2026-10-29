#!/usr/bin/env python3
"""Generate MEMORY.md (v4) from the family evidence pack with a local Ollama model.

Prompt-only variant of v3. The evidence pack is the one built by
build_family_evidence_v3.py (unchanged). The MAP and REDUCE prompts use the
official Frontier Memory consolidation instruction verbatim
(frontiermemory/src/frontier_memory/dream_task/instruction.md, SHA-256 pinned
below) followed by a short neutral framing line. No target-task description, no
interface/recipe requests, and no JSON output schema: the model writes free-form
memory notes, as the official instruction expects.

MAP: one /api/chat request per trajectory (condensed evidence only).
REDUCE: one request that merges the per-trajectory notes into MEMORY.md
(<= 8192 bytes). If the draft is too long, one shorter re-request is made; if it
is still too long, whole trailing bullets are dropped until it fits.
Thinking is disabled and any <think> blocks are stripped before saving.
Everything written here is generated from corpus text and stays in the job directory.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import time
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


OFFICIAL_INSTRUCTION_SHA256 = "a96e69af9427d75c8392f361b796ef294a7964b4910e687ac6e9afa2872c24e8"

MAP_FRAMING = (
    "Below is ONE trajectory from /evidence/inputs/{file}. Write candidate memory notes for "
    "/memory/MEMORY.md following the instructions above. Cite evidence as inputs/{file}#step=<N>."
)
REDUCE_FRAMING = (
    "Below are candidate notes extracted from each trajectory in /evidence/inputs/. Write the final "
    "/memory/MEMORY.md. Keep it at most 8192 bytes. Cite evidence as inputs/<file>#step=<N>."
)
REDUCE_SHORTER = (
    "The previous draft was {size} bytes, which is over the 8192-byte limit. Return the complete "
    "corrected /memory/MEMORY.md again, under 6900 bytes, keeping the most important content."
)

THINK_BLOCK = re.compile(r"<think>.*?</think>", re.DOTALL | re.IGNORECASE)
THINK_OPEN_TAIL = re.compile(r"<think>.*", re.DOTALL | re.IGNORECASE)
CITATION_TOKEN = re.compile(r"inputs/[^\s()\[\]\"'<>,;`]*")
CITATION = re.compile(r"inputs/(t\d{4}\.json)#step=(\d+)")
MAP_ATTEMPTS = 2
REDUCE_ATTEMPTS = 2
MIN_MAP_SUCCESS = 10
MEMORY_LIMIT = 8192


def strip_thinking(text: str) -> str:
    text = THINK_BLOCK.sub("", text)
    return THINK_OPEN_TAIL.sub("", text).strip()


def strip_outer_fence(text: str) -> tuple[str, bool]:
    lines = text.strip().splitlines()
    if len(lines) >= 3 and lines[0].startswith("```") and lines[-1].strip() == "```":
        return "\n".join(lines[1:-1]).strip(), True
    return text.strip(), False


def chat(api: str, model: str, context: int, temperature: float, num_predict: int, messages: list[dict]) -> tuple[str, dict]:
    body = {
        "model": model,
        "stream": False,
        "think": False,
        "keep_alive": "20m",
        "messages": messages,
        "options": {"temperature": temperature, "num_ctx": context, "num_predict": num_predict},
    }
    request = Request(
        api,
        data=json.dumps(body).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    started = time.monotonic()
    with urlopen(request, timeout=1800) as response:
        payload = json.load(response)
    wall = time.monotonic() - started
    message = payload.get("message") or {}
    raw = message.get("content") or ""
    meta = {
        "wall_seconds": round(wall, 3),
        "prompt_tokens": payload.get("prompt_eval_count"),
        "completion_tokens": payload.get("eval_count"),
        "total_duration_ns": payload.get("total_duration"),
        "done_reason": payload.get("done_reason"),
        "raw_chars": len(raw),
        "thinking_chars_discarded": len(message.get("thinking") or ""),
    }
    return strip_thinking(raw), meta


def citation_stats(text: str, file_name: str, steps: set[int]) -> dict:
    valid, invalid = 0, 0
    for token in CITATION_TOKEN.findall(text):
        token = token.rstrip(".:*")
        match = CITATION.fullmatch(token)
        if match and match.group(1) == file_name and int(match.group(2)) in steps:
            valid += 1
        else:
            invalid += 1
    return {"valid_citation_tokens": valid, "invalid_citation_tokens": invalid}


def run_map(args, index: dict, evidence_dir: Path, map_dir: Path, instruction: str) -> tuple[list[dict], list[dict]]:
    map_dir.mkdir(parents=True, exist_ok=True)
    successes: list[dict] = []
    summary: list[dict] = []
    for entry in index["files"]:
        file_name = Path(entry["file"]).name
        body = (evidence_dir.parent / entry["evidence_file"]).read_text(encoding="utf-8")
        prompt = instruction + "\n" + MAP_FRAMING.format(file=file_name) + "\n\n" + body
        messages = [{"role": "user", "content": prompt}]
        attempts: list[dict] = []
        notes = ""
        ok = False
        for attempt in range(1, MAP_ATTEMPTS + 1):
            record: dict = {"attempt": attempt, "prompt_sha256": hashlib.sha256(prompt.encode("utf-8")).hexdigest()}
            try:
                content, meta = chat(args.api, args.model, args.context, args.temperature, args.map_num_predict, messages)
                record.update(meta)
                record["content_chars"] = len(content)
                if not content.strip():
                    raise ValueError("empty map output")
                notes, fenced = strip_outer_fence(content)
                record["fence_stripped"] = fenced
                record.update(citation_stats(notes, file_name, set(entry["steps"])))
                record["status"] = "ok"
                ok = True
            except (HTTPError, URLError, ValueError, json.JSONDecodeError, KeyError) as error:
                record["status"] = "error"
                record["error"] = type(error).__name__ + ": " + str(error)[:300]
            attempts.append(record)
            if ok:
                break
        if ok:
            (map_dir / f"{entry['id']}.notes.txt").write_text(notes + "\n", encoding="utf-8", newline="\n")
            successes.append({"file": file_name, "notes": notes})
        (map_dir / f"{entry['id']}.attempts.json").write_text(json.dumps(attempts, indent=2) + "\n", encoding="utf-8")
        summary.append({"id": entry["id"], "succeeded": ok, "attempts": len(attempts)})
        print(json.dumps({"map": summary[-1]}), flush=True)
    return successes, summary


def bullet_indexes(lines: list[str]) -> list[int]:
    return [i for i, line in enumerate(lines) if line.startswith("- ") or line.startswith("* ")]


def run_reduce(args, successes: list[dict], instruction: str, reduce_dir: Path) -> tuple[str, dict]:
    reduce_dir.mkdir(parents=True, exist_ok=True)
    notes_block = "\n\n".join(f"=== candidate notes from inputs/{s['file']} ===\n{s['notes']}" for s in successes)
    prompt = instruction + "\n" + REDUCE_FRAMING + "\n\n" + notes_block
    messages = [{"role": "user", "content": prompt}]
    requests: list[dict] = []
    memory = None
    for round_number in (1, 2):
        if round_number == 2:
            size = len(memory.encode("utf-8"))
            messages = [
                {"role": "user", "content": prompt},
                {"role": "assistant", "content": memory},
                {"role": "user", "content": REDUCE_SHORTER.format(size=size)},
            ]
        draft = None
        for attempt in range(1, REDUCE_ATTEMPTS + 1):
            record = {"round": round_number, "attempt": attempt, "prompt_sha256": hashlib.sha256(prompt.encode("utf-8")).hexdigest()}
            try:
                content, meta = chat(args.api, args.model, args.context, args.temperature, args.reduce_num_predict, messages)
                record.update(meta)
                record["content_chars"] = len(content)
                draft, fenced = strip_outer_fence(content)
                record["fence_stripped"] = fenced
                if not draft:
                    raise ValueError("empty reduce output")
                record["bytes"] = len(draft.encode("utf-8"))
                record["status"] = "ok"
                requests.append(record)
                break
            except (HTTPError, URLError, ValueError, json.JSONDecodeError) as error:
                record["status"] = "error"
                record["error"] = type(error).__name__ + ": " + str(error)[:300]
                requests.append(record)
                draft = None
        if draft is None:
            if memory is None:
                raise SystemExit("REDUCE failed after retries; no MEMORY.md written")
            break
        memory = draft
        (reduce_dir / f"round-{round_number}.md").write_text(memory + "\n", encoding="utf-8", newline="\n")
        if len(memory.encode("utf-8")) <= MEMORY_LIMIT:
            break

    # Drop whole trailing bullets until the file fits the hard limit.
    removed = 0
    lines = memory.splitlines()
    while len(("\n".join(lines) + "\n").encode("utf-8")) > MEMORY_LIMIT:
        bullets = bullet_indexes(lines)
        if bullets:
            del lines[bullets[-1]]
        elif len(lines) > 1:
            del lines[-1]
        else:
            raise SystemExit("Cannot truncate memory to the byte limit")
        removed += 1
    final = "\n".join(lines).rstrip() + "\n"
    return final, {"requests": requests, "bytes_before_drop": len(memory.encode("utf-8")), "lines_removed_for_size": removed}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--job-dir", type=Path, required=True)
    parser.add_argument("--instruction", type=Path, required=True)
    parser.add_argument("--api", default="http://127.0.0.1:11434/api/chat")
    parser.add_argument("--model", required=True)
    parser.add_argument("--context", type=int, default=65536)
    parser.add_argument("--temperature", type=float, default=0.1)
    parser.add_argument("--map-num-predict", type=int, default=3000)
    parser.add_argument("--reduce-num-predict", type=int, default=3500)
    args = parser.parse_args()

    instruction_bytes = args.instruction.read_bytes()
    instruction_sha = hashlib.sha256(instruction_bytes).hexdigest()
    if instruction_sha != OFFICIAL_INSTRUCTION_SHA256:
        raise SystemExit(f"Unexpected official instruction SHA-256: {instruction_sha}")
    instruction = instruction_bytes.decode("utf-8")

    started = time.time()
    index = json.loads((args.job_dir / "evidence-index.json").read_text(encoding="utf-8"))
    evidence_dir = args.job_dir / "evidence"

    successes, map_summary = run_map(args, index, evidence_dir, args.job_dir / "map", instruction)
    succeeded = len(successes)
    if succeeded < MIN_MAP_SUCCESS:
        raise SystemExit(f"Only {succeeded} map requests succeeded; need at least {MIN_MAP_SUCCESS}")

    memory, reduce_meta = run_reduce(args, successes, instruction, args.job_dir / "reduce")
    memory_path = args.job_dir / "MEMORY.md"
    memory_path.write_text(memory, encoding="utf-8", newline="\n")

    map_records = []
    for entry in index["files"]:
        path = args.job_dir / "map" / f"{entry['id']}.attempts.json"
        if path.exists():
            map_records.extend(json.loads(path.read_text(encoding="utf-8")))
    all_records = map_records + reduce_meta["requests"]
    totals = {
        "requests": len(all_records),
        "requests_ok": sum(1 for r in all_records if r.get("status") == "ok"),
        "prompt_tokens": sum(int(r.get("prompt_tokens") or 0) for r in all_records),
        "completion_tokens": sum(int(r.get("completion_tokens") or 0) for r in all_records),
        "wall_seconds": round(sum(float(r.get("wall_seconds") or 0) for r in all_records), 3),
    }
    metrics = {
        "model": args.model,
        "context": args.context,
        "temperature": args.temperature,
        "map_num_predict": args.map_num_predict,
        "reduce_num_predict": args.reduce_num_predict,
        "thinking": "disabled (think=false; any <think> blocks stripped)",
        "instruction_sha256": instruction_sha,
        "map_framing": MAP_FRAMING,
        "reduce_framing": REDUCE_FRAMING,
        "map": {"trajectories": len(map_summary), "succeeded": succeeded, "per_trajectory": map_summary},
        "reduce": reduce_meta,
        "memory_bytes": len(memory.encode("utf-8")),
        "memory_limit_bytes": MEMORY_LIMIT,
        "totals": totals,
        "pipeline_wall_seconds": round(time.time() - started, 3),
    }
    (args.job_dir / "metrics.json").write_text(json.dumps(metrics, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"map_succeeded": succeeded, "memory_bytes": metrics["memory_bytes"], "totals": totals}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
