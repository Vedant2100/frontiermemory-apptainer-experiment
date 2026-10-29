#!/usr/bin/env python3
"""Generate FrontierMemory memory v5 from the whole pinned corpus with a local Ollama model.

The official generic prompt (frontiermemory/src/frontier_memory/dream_task/instruction.md)
is embedded verbatim in every request. Each request carries only the official prompt, a
minimal framing sentence, and corpus evidence from build_corpus_evidence_v5.py.

Subcommands (all write under --run-dir, which stays git-ignored):
  map       one request per trajectory (shardable: --shard I --shards N), resume-safe
  group     deterministic grouping of map notes by FAMILY label (CPU only)
  reduce    one request per group part -> memory/topics/<slug>.md
  finalize  index request -> memory/MEMORY.md, official checker, citation stats, digest

Thinking is disabled (think=false) and any <think> block is stripped before saving.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
import time
from collections import Counter, defaultdict
from pathlib import Path
from urllib.request import Request, urlopen

REPO = Path(__file__).resolve().parents[1]
INSTRUCTION_PATH = REPO / "frontiermemory/src/frontier_memory/dream_task/instruction.md"
INSTRUCTION_SHA256 = "a96e69af9427d75c8392f361b796ef294a7964b4910e687ac6e9afa2872c24e8"
CHECKER_PATH = REPO / "frontiermemory/src/frontier_memory/memory.py"

MAP_FRAMING = (
    "Below is ONE trajectory from /evidence/inputs/{file}. Write candidate notes for the memory "
    "described above (durable facts, methods, decision rules, validation checks, failed approaches; "
    "no final answers or literal artifacts). Start your output with one line "
    "'FAMILY: <short label for the kind of task this trajectory is about>'. "
    "Cite evidence as inputs/{file}#step=<N>."
)
REDUCE_FRAMING = (
    "Below are candidate notes from several trajectories in /evidence/inputs/. Write one memory topic "
    "file for this group of related evidence, at most 6,000 bytes, cited as inputs/<file>#step=<N>. "
    "Output only the Markdown file contents."
)
INDEX_FRAMING = (
    "Below are the topic files written for this memory, each with its path and headings. Write "
    "/memory/MEMORY.md as an index: for each topic file, what it covers and when to use it "
    "(imperative 'use when ...' phrasing), plus the most important cross-cutting lessons. Cite "
    "inputs/<file>#step=<N> only when a heading or excerpt shows it. Output only the Markdown file "
    "contents, at most 16,384 bytes."
)

MODEL = "qwen3.8:27b-mtp-q4_K_M"
CONTEXT = 65536
TEMPERATURE = 0.1
MAP_NUM_PREDICT = 900
REDUCE_NUM_PREDICT = 2048
INDEX_NUM_PREDICT = 4096
TOPIC_MAX_BYTES = 6000
INDEX_MAX_BYTES = 16384
GROUP_CHAR_BUDGET = 120000  # about 30-40K tokens of notes per reduce request
JACCARD_MERGE = 0.6
ATTEMPTS = 3
MAX_CONSECUTIVE_FAILURES = 5

THINK_BLOCK = re.compile(r"<think>.*?</think>", re.DOTALL | re.IGNORECASE)
THINK_OPEN_TAIL = re.compile(r"<think>.*", re.DOTALL | re.IGNORECASE)
FAMILY_LINE = re.compile(r"^\W*FAMILY\W*:\s*(.+?)\s*$", re.IGNORECASE | re.MULTILINE)
CITATION = re.compile(r"inputs/(t\d{4}\.jsonl?)#step=(\d+)")


def read_instruction() -> str:
    raw = INSTRUCTION_PATH.read_bytes()
    if hashlib.sha256(raw).hexdigest() != INSTRUCTION_SHA256:
        raise SystemExit("instruction.md does not match the pinned SHA-256")
    return raw.decode("utf-8")


def strip_thinking(text: str) -> str:
    text = THINK_BLOCK.sub("", text)
    text = THINK_OPEN_TAIL.sub("", text)
    return text.strip()


def chat(api: str, messages_text: str, num_predict: int) -> dict:
    payload = {
        "model": MODEL,
        "stream": False,
        "think": False,
        "messages": [{"role": "user", "content": messages_text}],
        "options": {"temperature": TEMPERATURE, "num_ctx": CONTEXT, "num_predict": num_predict},
    }
    request = Request(api, data=json.dumps(payload).encode("utf-8"),
                      headers={"Content-Type": "application/json"}, method="POST")
    started = time.monotonic()
    with urlopen(request, timeout=3600) as response:
        body = json.loads(response.read().decode("utf-8"))
    raw = str((body.get("message") or {}).get("content") or "")
    return {
        "text": strip_thinking(raw),
        "raw_chars": len(raw),
        "done_reason": body.get("done_reason"),
        "prompt_eval_count": body.get("prompt_eval_count", 0),
        "eval_count": body.get("eval_count", 0),
        "seconds": round(time.monotonic() - started, 2),
    }


def call_with_retries(api: str, prompt: str, num_predict: int, accept) -> tuple[dict | None, int, str]:
    """Return (result, attempts, last_error). result is None when every attempt failed."""
    last_error = ""
    for attempt in range(1, ATTEMPTS + 1):
        try:
            result = chat(api, prompt, num_predict)
            if accept(result["text"]):
                return result, attempt, ""
            last_error = "empty or rejected output"
        except Exception as exc:  # network or server errors are retried in-job
            last_error = f"{type(exc).__name__}: {exc}"[:300]
        time.sleep(15 * attempt)
    return None, ATTEMPTS, last_error


def write_json_atomic(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(value, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    os.replace(tmp, path)


def normalize_label(label: str) -> str:
    label = label.lower()
    label = re.sub(r"[^a-z0-9]+", " ", label)
    return re.sub(r"\s+", " ", label).strip()


def family_of(text: str) -> str:
    match = FAMILY_LINE.search(text)
    return match.group(1).strip().strip("*_` ") if match else ""


# ------------------------------------------------------------------------ map

def cmd_map(args: argparse.Namespace) -> int:
    instruction = read_instruction()
    index = json.loads((args.run_dir / "evidence-index.json").read_text(encoding="utf-8"))
    notes_dir = args.run_dir / "notes"
    notes_dir.mkdir(parents=True, exist_ok=True)
    files = sorted(index["files"], key=lambda f: f["id"])
    mine = [f for i, f in enumerate(files) if i % args.shards == args.shard]
    counters: Counter = Counter()
    consecutive_failures = 0
    started = time.monotonic()
    print(f"shard {args.shard}/{args.shards}: {len(mine)} trajectories", flush=True)
    for position, entry in enumerate(mine, start=1):
        out_path = notes_dir / f"{entry['id']}.json"
        if out_path.exists():
            counters["skipped_done"] += 1
            continue
        evidence = (args.run_dir / entry["evidence_file"]).read_text(encoding="utf-8")
        file_name = Path(entry["file"]).name
        prompt = f"{instruction}\n\n{MAP_FRAMING.format(file=file_name)}\n\n{evidence}"
        result, attempts, error = call_with_retries(
            args.api, prompt, MAP_NUM_PREDICT, lambda text: bool(text.strip()))
        if result is None:
            counters["failed"] += 1
            consecutive_failures += 1
            print(f"  FAIL {entry['id']}: {error}", flush=True)
            if consecutive_failures >= MAX_CONSECUTIVE_FAILURES:
                print("too many consecutive failures; stopping shard", flush=True)
                break
            continue
        consecutive_failures = 0
        text = result["text"]
        label = family_of(text)
        status = "ok" if label else "ok_unlabeled"
        counters[status] += 1
        counters["attempts_total"] += attempts
        counters["prompt_tokens"] += int(result["prompt_eval_count"])
        counters["output_tokens"] += int(result["eval_count"])
        counters["length_stops"] += int(result["done_reason"] == "length")
        write_json_atomic(out_path, {
            "id": entry["id"],
            "file": entry["file"],
            "outcome": entry["outcome"],
            "status": status,
            "family_raw": label,
            "family": normalize_label(label) or "unlabeled",
            "note": text,
            "citations": [f"inputs/{f}#step={s}" for f, s in CITATION.findall(text)],
            "attempts": attempts,
            "prompt_eval_count": result["prompt_eval_count"],
            "eval_count": result["eval_count"],
            "done_reason": result["done_reason"],
            "seconds": result["seconds"],
        })
        print(f"  [{position}/{len(mine)}] {entry['id']} {status} "
              f"in={result['prompt_eval_count']} out={result['eval_count']} {result['seconds']}s", flush=True)
    summary = {
        "shard": args.shard,
        "shards": args.shards,
        "assigned": len(mine),
        "counters": dict(counters),
        "wall_seconds": round(time.monotonic() - started, 1),
        "model": MODEL,
        "context": CONTEXT,
        "temperature": TEMPERATURE,
        "think": False,
        "num_predict": MAP_NUM_PREDICT,
    }
    write_json_atomic(args.run_dir / "logs" / f"map-shard-{args.shard}-of-{args.shards}.json", summary)
    print(json.dumps(summary, indent=2), flush=True)
    return 0 if consecutive_failures < MAX_CONSECUTIVE_FAILURES else 2


# ---------------------------------------------------------------------- group

def tokens_of(label: str) -> set[str]:
    return set(label.split())


def cmd_group(args: argparse.Namespace) -> dict:
    notes = []
    for path in sorted((args.run_dir / "notes").glob("*.json")):
        record = json.loads(path.read_text(encoding="utf-8"))
        if record.get("note", "").strip():
            notes.append(record)
    labels = sorted({n["family"] for n in notes})
    parent = {label: label for label in labels}

    def find(x: str) -> str:
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    for i, a in enumerate(labels):
        ta = tokens_of(a)
        for b in labels[i + 1:]:
            tb = tokens_of(b)
            if not ta or not tb:
                continue
            jaccard = len(ta & tb) / len(ta | tb)
            if jaccard >= JACCARD_MERGE:
                parent[find(b)] = find(a)

    clusters: dict[str, list[dict]] = defaultdict(list)
    for note in notes:
        clusters[find(note["family"])].append(note)

    groups = []
    for root, members in clusters.items():
        label_counts = Counter(m["family"] for m in members)
        canonical = sorted(label_counts.items(), key=lambda kv: (-kv[1], kv[0]))[0][0]
        members.sort(key=lambda m: m["id"])
        parts: list[list[dict]] = [[]]
        used = 0
        for member in members:
            size = len(member["note"]) + 200
            if parts[-1] and used + size > GROUP_CHAR_BUDGET:
                parts.append([])
                used = 0
            parts[-1].append(member)
            used += size
        for part_index, part in enumerate(parts, start=1):
            groups.append({
                "label": canonical,
                "labels_merged": sorted(label_counts),
                "part": part_index,
                "parts": len(parts),
                "ids": [m["id"] for m in part],
                "chars": sum(len(m["note"]) + 200 for m in part),
            })
    groups.sort(key=lambda g: (g["label"], g["part"]))
    for number, group in enumerate(groups, start=1):
        slug = re.sub(r"[^a-z0-9]+", "-", group["label"]).strip("-")[:48] or "topic"
        group["slug"] = f"g{number:03d}-{slug}" + (f"-p{group['part']}" if group["parts"] > 1 else "")
    summary = {
        "notes": len(notes),
        "raw_labels": len({n["family_raw"] for n in notes}),
        "normalized_labels": len(labels),
        "clusters_after_merge": len(clusters),
        "groups_parts": len(groups),
        "split_clusters": sum(1 for g in groups if g["parts"] > 1),
        "largest_group_notes": max(len(g["ids"]) for g in groups),
        "largest_group_chars": max(g["chars"] for g in groups),
        "smallest_group_notes": min(len(g["ids"]) for g in groups),
        "singleton_groups": sum(1 for g in groups if len(g["ids"]) == 1),
        "unlabeled_notes": sum(1 for n in notes if n["family"] == "unlabeled"),
    }
    write_json_atomic(args.run_dir / "groups.json", {"summary": summary, "groups": groups})
    print(json.dumps(summary, indent=2))
    return summary


# --------------------------------------------------------------------- reduce

def truncate_bytes(text: str, limit: int) -> tuple[str, bool]:
    raw = text.encode("utf-8")
    if len(raw) <= limit:
        return text, False
    cut = raw[:limit].decode("utf-8", errors="ignore")
    newline = cut.rfind("\n")
    if newline > limit // 2:
        cut = cut[:newline]
    return cut.rstrip() + "\n", True


def cmd_reduce(args: argparse.Namespace) -> int:
    instruction = read_instruction()
    groups = json.loads((args.run_dir / "groups.json").read_text(encoding="utf-8"))["groups"]
    notes = {}
    for group in groups:
        for note_id in group["ids"]:
            if note_id not in notes:
                notes[note_id] = json.loads((args.run_dir / "notes" / f"{note_id}.json").read_text(encoding="utf-8"))
    topics_dir = args.run_dir / "memory" / "topics"
    topics_dir.mkdir(parents=True, exist_ok=True)
    report = []
    counters: Counter = Counter()
    started = time.monotonic()
    for position, group in enumerate(groups, start=1):
        out_path = topics_dir / f"{group['slug']}.md"
        meta_path = args.run_dir / "reduce" / f"{group['slug']}.json"
        if out_path.exists() and meta_path.exists():
            counters["skipped_done"] += 1
            report.append(json.loads(meta_path.read_text(encoding="utf-8")))
            continue
        blocks = []
        for note_id in group["ids"]:
            note = notes[note_id]
            blocks.append(f"### FILE: {note['file']}\n{note['note']}")
        prompt = (f"{instruction}\n\n{REDUCE_FRAMING}\n\nGroup: {group['label']}\n\n" + "\n\n".join(blocks))
        result, attempts, error = call_with_retries(
            args.api, prompt, REDUCE_NUM_PREDICT, lambda text: len(text.strip()) > 40)
        if result is None:
            counters["failed"] += 1
            print(f"  FAIL {group['slug']}: {error}", flush=True)
            continue
        body, truncated = truncate_bytes(result["text"], TOPIC_MAX_BYTES)
        out_path.write_text(body, encoding="utf-8")
        record = {
            "slug": group["slug"],
            "label": group["label"],
            "notes": len(group["ids"]),
            "attempts": attempts,
            "bytes": len(body.encode("utf-8")),
            "truncated_to_limit": truncated,
            "prompt_eval_count": result["prompt_eval_count"],
            "eval_count": result["eval_count"],
            "done_reason": result["done_reason"],
            "seconds": result["seconds"],
        }
        write_json_atomic(meta_path, record)
        report.append(record)
        counters["ok"] += 1
        counters["prompt_tokens"] += int(result["prompt_eval_count"])
        counters["output_tokens"] += int(result["eval_count"])
        counters["truncated_to_limit"] += int(truncated)
        print(f"  [{position}/{len(groups)}] {group['slug']} notes={len(group['ids'])} "
              f"bytes={record['bytes']} {result['seconds']}s", flush=True)
    summary = {"groups": len(groups), "counters": dict(counters),
               "wall_seconds": round(time.monotonic() - started, 1), "topics": report}
    write_json_atomic(args.run_dir / "logs" / "reduce-summary.json", summary)
    print(json.dumps({k: v for k, v in summary.items() if k != "topics"}, indent=2))
    return 0 if counters["failed"] == 0 else 2


# ------------------------------------------------------------------- finalize

def topic_outline(path: Path) -> str:
    lines = path.read_text(encoding="utf-8").splitlines()
    headings = [line.strip() for line in lines if line.startswith("#")][:12]
    first = next((line.strip() for line in lines if line.strip()), "")
    text = f"- topics/{path.name}: first line: {first[:200]} | headings: {' / '.join(headings)[:500]}"
    return text


def cmd_finalize(args: argparse.Namespace) -> int:
    instruction = read_instruction()
    memory_dir = args.run_dir / "memory"
    topics = sorted((memory_dir / "topics").glob("*.md"))
    outline = "\n".join(topic_outline(p) for p in topics)
    prompt = f"{instruction}\n\n{INDEX_FRAMING}\n\n{outline}"
    result, attempts, error = call_with_retries(
        args.api, prompt, INDEX_NUM_PREDICT, lambda text: len(text.strip()) > 80)
    if result is None:
        raise SystemExit(f"index request failed: {error}")
    body, truncated = truncate_bytes(result["text"], INDEX_MAX_BYTES)
    (memory_dir / "MEMORY.md").write_text(body, encoding="utf-8")
    index_meta = {"attempts": attempts, "bytes": len(body.encode("utf-8")), "truncated_to_limit": truncated,
                  "topics": len(topics), "prompt_eval_count": result["prompt_eval_count"],
                  "eval_count": result["eval_count"], "done_reason": result["done_reason"],
                  "seconds": result["seconds"]}
    write_json_atomic(args.run_dir / "logs" / "index-summary.json", index_meta)

    # Official format check (the checker is standard library only).
    report_path = args.run_dir / "logs" / "check-memory-report.json"
    check = subprocess.run([sys.executable, "-I", str(CHECKER_PATH), str(memory_dir), "--report", str(report_path)],
                           capture_output=True, text=True)
    report = json.loads(report_path.read_text(encoding="utf-8"))

    # Citation statistics (informational).
    evidence_index = json.loads((args.run_dir / "evidence-index.json").read_text(encoding="utf-8"))
    steps = {Path(f["file"]).name: set(f["step_ids"]) for f in evidence_index["files"]}
    total = resolved = file_ok = 0
    unresolved_examples: list[str] = []
    for path in [memory_dir / "MEMORY.md", *topics]:
        for name, step in CITATION.findall(path.read_text(encoding="utf-8")):
            total += 1
            if name in steps:
                file_ok += 1
                if int(step) in steps[name]:
                    resolved += 1
                    continue
            if len(unresolved_examples) < 5:
                unresolved_examples.append(f"{path.name}: inputs/{name}#step={step}")
    citations = {"total": total, "file_exists": file_ok, "resolved": resolved,
                 "resolved_fraction": round(resolved / total, 4) if total else None,
                 "unresolved_examples_are_paths_only": unresolved_examples}
    summary = {"checker_exit": check.returncode, "checker": report, "citations": citations,
               "index": index_meta, "topic_files": len(topics)}
    write_json_atomic(args.run_dir / "logs" / "finalize-summary.json", summary)
    print(json.dumps({"checker_ok": report["ok"], "errors": report["errors"],
                      "total_bytes": report["total_bytes"], "file_count": report["file_count"],
                      "topic_files": len(topics), "citations": {k: v for k, v in citations.items()
                                                               if k != "unresolved_examples_are_paths_only"}},
                     indent=2))
    return 0 if report["ok"] else 1


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)
    for name in ("map", "group", "reduce", "finalize"):
        p = sub.add_parser(name)
        p.add_argument("--run-dir", type=Path, required=True)
        p.add_argument("--api", default="http://127.0.0.1:11434/api/chat")
        if name == "map":
            p.add_argument("--shard", type=int, required=True)
            p.add_argument("--shards", type=int, required=True)
    args = parser.parse_args()
    if args.command == "map":
        return cmd_map(args)
    if args.command == "group":
        cmd_group(args)
        return 0
    if args.command == "reduce":
        return cmd_reduce(args)
    return cmd_finalize(args)


if __name__ == "__main__":
    sys.exit(main())
