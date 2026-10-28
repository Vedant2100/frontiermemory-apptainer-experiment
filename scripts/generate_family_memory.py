#!/usr/bin/env python3
"""Generate a cited memory file from the family evidence pack with a local Ollama model.

MAP: one /api/chat request per trajectory (condensed evidence only).
REDUCE: one request that merges the validated lessons into MEMORY.md.
Thinking output is disabled and any <think> blocks are stripped before saving.
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


MAP_SYSTEM = """You extract reusable engineering lessons from one recorded trajectory of an autonomous coding agent working in a terminal sandbox on a software task. You are given the recorded outcome of the run, the initial instruction, and a condensed step-numbered transcript.

Write up to 6 concrete lessons that would help a future agent attempting a similar task.
- For a PASS run, describe what the agent did that worked.
- For a FAIL run, describe what caused the failure or what went wrong, and how to avoid it.
- Prefer concrete specifics: library APIs and version differences, exact file and output contracts, data-handling details, parameter values, pitfalls and their fixes, and verification steps.
- Avoid generic workflow advice such as "plan carefully" or "test your code".
- Do not invent facts that are not in the transcript.
- Every lesson must cite the step or steps that support it, using exactly this form: inputs/<file>#step=<N>, where <file> is the file named in the input and <N> is a step number that appears in the transcript.

Output only a JSON object of this shape:
{"lessons": [{"lesson": "one or two sentences", "citations": ["inputs/<file>#step=<N>"]}]}"""

REDUCE_SYSTEM = """You merge lessons drawn from several recorded coding-agent trajectories into one memory file for future agents that attempt similar tasks.

The input is a numbered list of lessons. Each lesson has a recorded outcome (PASS or FAIL) and citations of the form inputs/<file>#step=<N>.

Output only a JSON object of this shape:
{"title": "short title", "sections": [{"theme": "short theme name", "bullets": [{"text": "one concise self-contained sentence or two, with the supporting citations written inline in parentheses, copied exactly from the source lessons", "source_ids": ["L01"]}]}]}

Rules:
- Group bullets into 3 to 6 themes. Merge duplicate lessons.
- Keep only concrete, reusable, specific lessons. Drop generic advice.
- Each bullet must contain at least one citation copied exactly from its source lessons. Never invent or alter citations.
- Each bullet must be a single line of text with no line breaks.
- Keep every bullet under 260 characters.
- The whole file must stay under the byte limit given in the request."""

THINK_BLOCK = re.compile(r"<think>.*?</think>", re.DOTALL | re.IGNORECASE)
THINK_OPEN_TAIL = re.compile(r"<think>.*", re.DOTALL | re.IGNORECASE)
CITATION_TOKEN = re.compile(r"inputs/[^\s()\[\]\"'<>,;]*")
CITATION = re.compile(r"inputs/(t\d{4}\.json)#step=(\d+)")
MAX_LESSONS = 6
MAP_ATTEMPTS = 2
REDUCE_ATTEMPTS = 2
MIN_MAP_SUCCESS = 10
MEMORY_LIMIT = 4096
FIRST_TARGET = 3600
SECOND_TARGET = 3200


def strip_thinking(text: str) -> str:
    text = THINK_BLOCK.sub("", text)
    return THINK_OPEN_TAIL.sub("", text).strip()


def parse_json_object(text: str) -> dict:
    try:
        value = json.loads(text)
    except json.JSONDecodeError:
        start, end = text.find("{"), text.rfind("}")
        if start < 0 or end <= start:
            raise
        value = json.loads(text[start : end + 1])
    if not isinstance(value, dict):
        raise ValueError("model output is not a JSON object")
    return value


def chat(api: str, model: str, context: int, temperature: float, num_predict: int, messages: list[dict]) -> tuple[str, dict]:
    body = {
        "model": model,
        "stream": False,
        "think": False,
        "format": "json",
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
        "load_duration_ns": payload.get("load_duration"),
        "prompt_eval_duration_ns": payload.get("prompt_eval_duration"),
        "eval_duration_ns": payload.get("eval_duration"),
        "done_reason": payload.get("done_reason"),
        "raw_chars": len(raw),
        "thinking_chars_discarded": len(message.get("thinking") or ""),
    }
    return strip_thinking(raw), meta


def validate_map_output(value: dict, file_name: str, steps: set[int]) -> tuple[list[dict], dict]:
    raw_lessons = value.get("lessons")
    if not isinstance(raw_lessons, list):
        raise ValueError("missing lessons list")
    accepted: list[dict] = []
    dropped = {"lessons_not_dict": 0, "empty_text": 0, "no_valid_citation": 0, "invalid_citation_tokens": 0}
    for item in raw_lessons[:MAX_LESSONS]:
        if not isinstance(item, dict):
            dropped["lessons_not_dict"] += 1
            continue
        text = str(item.get("lesson") or "").strip()
        if not text:
            dropped["empty_text"] += 1
            continue
        raw_citations = item.get("citations") or []
        if not isinstance(raw_citations, list):
            raw_citations = []
        valid = []
        for citation in raw_citations:
            match = CITATION.fullmatch(str(citation).strip())
            if match and match.group(1) == file_name and int(match.group(2)) in steps:
                valid.append(f"inputs/{file_name}#step={int(match.group(2))}")
            else:
                dropped["invalid_citation_tokens"] += 1
        valid = list(dict.fromkeys(valid))
        if not valid:
            dropped["no_valid_citation"] += 1
            continue
        accepted.append({"lesson": " ".join(text.split()), "citations": valid})
    return accepted, dropped


def run_map(args, index: dict, evidence_dir: Path, map_dir: Path) -> list[dict]:
    map_dir.mkdir(parents=True, exist_ok=True)
    all_lessons: list[dict] = []
    summary = []
    for entry in index["files"]:
        file_name = Path(entry["file"]).name
        text = (evidence_dir.parent / entry["evidence_file"]).read_text(encoding="utf-8")
        messages = [
            {"role": "system", "content": MAP_SYSTEM},
            {
                "role": "user",
                "content": (
                    f"Recorded outcome of this run: {entry['outcome']}\n"
                    f"File to cite: inputs/{file_name}\n\n"
                    f"{text}\n\nReturn the JSON object now."
                ),
            },
        ]
        attempts = []
        accepted: list[dict] = []
        dropped: dict = {}
        ok = False
        for attempt in range(1, MAP_ATTEMPTS + 1):
            record: dict = {"attempt": attempt}
            try:
                content, meta = chat(args.api, args.model, args.context, args.temperature, args.map_num_predict, messages)
                record.update(meta)
                record["content_chars"] = len(content)
                parsed = parse_json_object(content)
                accepted, dropped = validate_map_output(parsed, file_name, set(entry["steps"]))
                if not accepted:
                    raise ValueError("no lesson with a valid citation")
                record["status"] = "ok"
                ok = True
            except (HTTPError, URLError, ValueError, json.JSONDecodeError, KeyError) as error:
                record["status"] = "error"
                record["error"] = type(error).__name__ + ": " + str(error)[:300]
            attempts.append(record)
            if ok:
                break
        result = {
            "file": entry["file"],
            "id": entry["id"],
            "outcome": entry["outcome"],
            "succeeded": ok,
            "lessons": accepted,
            "dropped": dropped,
            "attempts": attempts,
        }
        (map_dir / f"{entry['id']}.json").write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
        summary.append({"id": entry["id"], "outcome": entry["outcome"], "succeeded": ok, "lessons": len(accepted), "attempts": len(attempts)})
        print(json.dumps({"map": summary[-1]}), flush=True)
        if ok:
            all_lessons.extend({**lesson, "id": entry["id"], "outcome": entry["outcome"]} for lesson in accepted)
    return all_lessons, summary


def lesson_listing(lessons: list[dict]) -> str:
    lines = []
    for number, lesson in enumerate(lessons, start=1):
        cites = "; ".join(lesson["citations"])
        lines.append(f"L{number:02d} [{lesson['outcome']}] {lesson['lesson']} Citations: {cites}")
    return "\n".join(lines)


def render(title: str, sections: list[dict]) -> str:
    lines = [f"# {title}", "", "Citations refer to inputs/<file>#step=<N> in the family evidence pack. [FAIL-derived] marks bullets whose cited runs failed.", ""]
    for section in sections:
        if not section["bullets"]:
            continue
        lines.append(f"## {section['theme']}")
        for bullet in section["bullets"]:
            lines.append(f"- {bullet['label']} {bullet['text']}")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def build_sections(reduce_json: dict, outcome_by_file: dict, valid_refs: set) -> tuple[list[dict], dict]:
    stats = {"bullets_in": 0, "bullets_kept": 0, "dropped_no_valid_citation": 0}
    sections = []
    for section in reduce_json.get("sections") or []:
        if not isinstance(section, dict):
            continue
        theme = " ".join(str(section.get("theme") or "").split())[:120] or "Lessons"
        bullets = []
        for bullet in section.get("bullets") or []:
            stats["bullets_in"] += 1
            if not isinstance(bullet, dict):
                stats["dropped_no_valid_citation"] += 1
                continue
            text = " ".join(str(bullet.get("text") or "").split())
            tokens = CITATION_TOKEN.findall(text)
            citations = [t.rstrip(".") for t in tokens]
            if not citations or any(not CITATION.fullmatch(c) or c not in valid_refs for c in citations):
                stats["dropped_no_valid_citation"] += 1
                continue
            outcomes = {outcome_by_file[CITATION.fullmatch(c).group(1)] for c in citations}
            if outcomes == {"FAIL"}:
                label = "[FAIL-derived]"
            elif outcomes == {"PASS"}:
                label = "[PASS-derived]"
            else:
                label = "[mixed PASS and FAIL runs]"
            bullets.append({"text": text, "label": label, "citations": citations})
            stats["bullets_kept"] += 1
        sections.append({"theme": theme, "bullets": bullets})
    title = " ".join(str(reduce_json.get("title") or "").split())[:120] or "Word2Vec pipeline memory"
    return sections, {"title": title, **stats}


def run_reduce(args, lessons: list[dict], outcome_by_file: dict, valid_refs: set, reduce_dir: Path) -> tuple[str, dict]:
    reduce_dir.mkdir(parents=True, exist_ok=True)
    listing = lesson_listing(lessons)
    requests: list[dict] = []
    limits = [FIRST_TARGET, SECOND_TARGET]
    final_sections, final_meta = None, None
    final_render = None
    for round_number, limit in enumerate(limits, start=1):
        messages = [
            {"role": "system", "content": REDUCE_SYSTEM},
            {
                "role": "user",
                "content": (
                    f"The final file must be at most {limit} bytes of UTF-8.\n\n"
                    f"Lessons ({len(lessons)}):\n{listing}\n\nReturn the JSON object now."
                ),
            },
        ]
        if round_number > 1:
            messages.append(
                {
                    "role": "user",
                    "content": (
                        f"The previous draft was {len(final_render.encode('utf-8'))} bytes, which is too long. "
                        f"Return a shorter version under {limit} bytes with fewer, more important bullets."
                    ),
                }
            )
        parsed = None
        for attempt in range(1, REDUCE_ATTEMPTS + 1):
            record = {"round": round_number, "attempt": attempt, "byte_limit": limit}
            try:
                content, meta = chat(args.api, args.model, args.context, args.temperature, args.reduce_num_predict, messages)
                record.update(meta)
                record["content_chars"] = len(content)
                parsed = parse_json_object(content)
                if not isinstance(parsed.get("sections"), list):
                    raise ValueError("missing sections list")
                record["status"] = "ok"
                requests.append(record)
                break
            except (HTTPError, URLError, ValueError, json.JSONDecodeError) as error:
                record["status"] = "error"
                record["error"] = type(error).__name__ + ": " + str(error)[:300]
                requests.append(record)
                parsed = None
        if parsed is None:
            raise SystemExit("REDUCE failed after retries; no MEMORY.md written")
        (reduce_dir / f"round-{round_number}.json").write_text(json.dumps(parsed, indent=2) + "\n", encoding="utf-8")
        sections, meta = build_sections(parsed, outcome_by_file, valid_refs)
        text = render(meta["title"], sections)
        final_sections, final_meta, final_render = sections, meta, text
        if len(text.encode("utf-8")) <= MEMORY_LIMIT:
            break

    # Truncate whole bullets from the end until the file fits the hard limit.
    removed = 0
    while len(final_render.encode("utf-8")) > MEMORY_LIMIT:
        for section in reversed(final_sections):
            if section["bullets"]:
                section["bullets"].pop()
                removed += 1
                break
        else:
            raise SystemExit("Cannot truncate memory to the byte limit")
        final_sections = [s for s in final_sections if s["bullets"]]
        final_render = render(final_meta["title"], final_sections)
    final_meta.update({"bullets_truncated_for_size": removed})
    return final_render, {"requests": requests, **final_meta}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--job-dir", type=Path, required=True)
    parser.add_argument("--api", default="http://127.0.0.1:11434/api/chat")
    parser.add_argument("--model", required=True)
    parser.add_argument("--context", type=int, default=65536)
    parser.add_argument("--temperature", type=float, default=0.1)
    parser.add_argument("--map-num-predict", type=int, default=1400)
    parser.add_argument("--reduce-num-predict", type=int, default=2400)
    args = parser.parse_args()

    started = time.time()
    index = json.loads((args.job_dir / "evidence-index.json").read_text(encoding="utf-8"))
    evidence_dir = args.job_dir / "evidence"
    outcome_by_file = {Path(f["file"]).name: f["outcome"] for f in index["files"]}
    valid_refs = {f"inputs/{Path(f['file']).name}#step={s}" for f in index["files"] for s in f["steps"]}

    lessons, map_summary = run_map(args, index, evidence_dir, args.job_dir / "map")
    succeeded = sum(1 for m in map_summary if m["succeeded"])
    if succeeded < MIN_MAP_SUCCESS:
        raise SystemExit(f"Only {succeeded} map requests succeeded; need at least {MIN_MAP_SUCCESS}")

    memory, reduce_meta = run_reduce(args, lessons, outcome_by_file, valid_refs, args.job_dir / "reduce")
    memory_path = args.job_dir / "MEMORY.md"
    memory_path.write_text(memory, encoding="utf-8", newline="\n")

    map_records = []
    for entry in index["files"]:
        path = args.job_dir / "map" / f"{entry['id']}.json"
        map_records.extend(json.loads(path.read_text(encoding="utf-8"))["attempts"])
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
        "thinking": "disabled (think=false; any <think> blocks stripped)",
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
