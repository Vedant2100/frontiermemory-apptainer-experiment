#!/usr/bin/env python3
"""Helpers for scripts/run_codex_word2vec_trial.sh (Codex CLI harness, Word2Vec task).

Writes counts and status only. It never copies prompts, model output, commands,
memory text, or workspace contents into records. Verifier parsing, failure
categories, and validity rules (protocol-v2.md, decision D5') are reused from
scripts/word2vec_ab_v2_records.py so the Codex arm is scored like the OpenHands arm.

Subcommands:
  render-prompt     substitute the single {{ instruction }} placeholder in the shared base template
  summarize-events  count-only summary of a `codex exec --json` event stream
  trial-record      write one sanitized trial-record.json
  aggregate         collect trial records for one job
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from word2vec_ab_v2_records import (  # noqa: E402
    CASES_TOTAL,
    categorize,
    parse_verifier,
    read_json,
)

SCHEMA = "word2vec-codex-trial-record/1"
USAGE_KEYS = ("input_tokens", "cached_input_tokens", "output_tokens", "reasoning_output_tokens")
PLACEHOLDER = "{{ instruction }}"


def read_text_or_empty(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


# ------------------------------------------------------------ render-prompt
def cmd_render_prompt(args: argparse.Namespace) -> int:
    template = Path(args.template).read_text(encoding="utf-8")
    instruction = Path(args.instruction).read_text(encoding="utf-8")
    if template.count(PLACEHOLDER) != 1:
        raise SystemExit("base template must contain exactly one {{ instruction }} placeholder")
    Path(args.output).write_text(template.replace(PLACEHOLDER, instruction), encoding="utf-8")
    print(sha256_file(Path(args.output)))
    return 0


# --------------------------------------------------------- summarize-events
def cmd_summarize_events(args: argparse.Namespace) -> int:
    path = Path(args.events)
    event_types: Counter = Counter()
    item_types: Counter = Counter()
    stats: Counter = Counter()
    turn_usage = {k: 0 for k in USAGE_KEYS}
    any_usage = {k: 0 for k in USAGE_KEYS}
    turn_fields: set = set()
    any_fields: set = set()
    saw_turn_usage = saw_any_usage = False
    lines = parse_errors = 0

    if path.is_file():
        with path.open(encoding="utf-8", errors="replace") as handle:
            for raw in handle:
                raw = raw.strip()
                if not raw:
                    continue
                lines += 1
                try:
                    event = json.loads(raw)
                except json.JSONDecodeError:
                    parse_errors += 1
                    continue
                if not isinstance(event, dict):
                    parse_errors += 1
                    continue
                etype = str(event.get("type", "<missing>"))
                event_types[etype] += 1
                if etype == "turn.started":
                    stats["turns_started"] += 1
                elif etype == "turn.completed":
                    stats["turns_completed"] += 1
                elif etype == "turn.failed":
                    stats["turns_failed"] += 1

                usage = event.get("usage")
                if isinstance(usage, dict):
                    saw_any_usage = True
                    for key in USAGE_KEYS:
                        value = usage.get(key)
                        if isinstance(value, (int, float)) and not isinstance(value, bool):
                            any_fields.add(key)
                            any_usage[key] += int(value)
                    if etype == "turn.completed":
                        saw_turn_usage = True
                        for key in USAGE_KEYS:
                            value = usage.get(key)
                            if isinstance(value, (int, float)) and not isinstance(value, bool):
                                turn_fields.add(key)
                                turn_usage[key] += int(value)

                item = event.get("item")
                if isinstance(item, dict) and etype == "item.completed":
                    itype = str(item.get("type", "<missing>"))
                    item_types[itype] += 1
                    stats["items_completed"] += 1
                    if itype == "command_execution":
                        stats["commands_executed"] += 1
                    elif itype == "file_change":
                        stats["file_change_items"] += 1
                        changes = item.get("changes")
                        stats["file_change_entries"] += len(changes) if isinstance(changes, list) else 1
                    elif itype == "agent_message":
                        stats["agent_messages"] += 1

    if saw_turn_usage:
        usage_out, fields, source = turn_usage, turn_fields, "turn.completed"
    elif saw_any_usage:
        usage_out, fields, source = any_usage, any_fields, "any_usage_event"
    else:
        usage_out, fields, source = {}, set(), None
    usage_record = {k: (usage_out[k] if k in fields else None) for k in USAGE_KEYS} if source else \
        {k: None for k in USAGE_KEYS}

    summary = {
        "lines": lines,
        "parse_errors": parse_errors,
        "event_type_counts": dict(sorted(event_types.items())),
        "item_type_counts": dict(sorted(item_types.items())),
        "turns_started": stats["turns_started"],
        "turns_completed": stats["turns_completed"],
        "turns_failed": stats["turns_failed"],
        "items_completed": stats["items_completed"],
        "commands_executed": stats["commands_executed"],
        "file_change_items": stats["file_change_items"],
        "file_change_entries": stats["file_change_entries"],
        "agent_messages": stats["agent_messages"],
        "usage": usage_record,
        "usage_source": source,
    }
    Path(args.output).write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    return 0


# ------------------------------------------------------------- trial-record
def cmd_trial_record(args: argparse.Namespace) -> int:
    tdir = Path(args.trial_dir)
    gdir = Path(args.grade_dir)
    job_dir = Path(args.job_dir)
    run_meta = read_json(tdir / "run-meta.json") or {}
    events = read_json(tdir / "events-summary.json") or {}

    harbor_trials = sorted(p for p in job_dir.glob("*") if p.is_dir()) if job_dir.is_dir() else []
    harbor_trial = harbor_trials[0] if harbor_trials else None
    raw_result = read_json(harbor_trial / "result.json") if harbor_trial else None
    result = raw_result or {}

    solution = gdir / "workspace" / "solution.py"
    solution_present = solution.is_file() and solution.stat().st_size > 0

    verifier = parse_verifier(harbor_trial / "verifier" / "test-stdout.txt") if harbor_trial else \
        parse_verifier(Path("/nonexistent"))
    reward = None
    if result.get("verifier_result"):
        reward = (result["verifier_result"].get("rewards") or {}).get("reward")
    if reward is None and harbor_trial and (harbor_trial / "verifier" / "reward.txt").is_file():
        try:
            reward = float((harbor_trial / "verifier" / "reward.txt").read_text().strip())
        except ValueError:
            reward = None

    exc = result.get("exception_info")
    exc_type = exc.get("exception_type") if isinstance(exc, dict) else None
    try:
        harbor_exit = int(args.harbor_exit)
    except ValueError:
        harbor_exit = None

    turns_started = int(events.get("turns_started", 0) or 0)
    items_completed = int(events.get("items_completed", 0) or 0)
    category, invalid_reason = categorize(
        harbor_exit=harbor_exit, raw_result=raw_result, exc_type=exc_type,
        has_exception=bool(exc), reward=reward, verifier=verifier,
        artifact_present=solution_present, agent_steps=items_completed,
        model_requests=turns_started, expect_model=True)
    if category == "CONTRACT_COLLECTION_ERROR" and harbor_trial is not None:
        # Split collection errors: a missing attribute is the agent's contract (CONTRACT_COLLECTION_ERROR);
        # anything else during collection, e.g. an import LookupError, is COLLECTION_ERROR_OTHER.
        # Only the error class name is inspected here. No verifier text is copied into the record.
        verifier_text = read_text_or_empty(harbor_trial / "verifier" / "test-stdout.txt")
        if "AttributeError" not in verifier_text:
            category = "COLLECTION_ERROR_OTHER"
    valid = category != "INVALID_INFRA"
    if valid:
        strict_reward = 1.0 if category == "PASS" else 0.0
        cases_passed = 0 if category in ("NO_ARTIFACT", "CONTRACT_COLLECTION_ERROR", "COLLECTION_ERROR_OTHER") \
            else min(verifier["passed"], CASES_TOTAL)
    else:
        strict_reward = cases_passed = None

    usage = events.get("usage") or {}
    record = {
        "schema": SCHEMA,
        "job_id": args.job_id,
        "trial_index": args.index,
        "condition": args.condition,
        "harness": "codex-cli",
        "model": args.model,
        "reasoning_effort": args.reasoning,
        "codex_version": run_meta.get("codex_version"),
        "valid": valid,
        "failure_category": category,
        "invalid_reason": invalid_reason,
        "strict_reward": strict_reward,
        "cases_passed_of_6": cases_passed,
        "cases_total": CASES_TOTAL,
        "verifier_collected": verifier["collected"],
        "verifier_passed": verifier["passed"],
        "verifier_failed": verifier["failed"],
        "verifier_errors": verifier["errors"],
        "verifier_collection_error": verifier["collection_error"],
        "verifier_network_mode": "public",
        "artifact_solution_py_present": solution_present,
        "harbor_grading_exit_code": harbor_exit,
        "harbor_exception_type": exc_type,
        "reward_raw": reward,
        "codex_exit_code": run_meta.get("codex_exit_code"),
        "timed_out": run_meta.get("timed_out"),
        "agent_timeout_sec": args.agent_timeout_sec,
        "agent_wall_sec": run_meta.get("agent_wall_sec"),
        "turns_started": turns_started,
        "turns_completed": events.get("turns_completed"),
        "turns_failed": events.get("turns_failed"),
        "commands_executed": events.get("commands_executed"),
        "file_change_items": events.get("file_change_items"),
        "file_change_entries": events.get("file_change_entries"),
        "items_completed": items_completed,
        "input_tokens": usage.get("input_tokens"),
        "cached_input_tokens": usage.get("cached_input_tokens"),
        "output_tokens": usage.get("output_tokens"),
        "reasoning_output_tokens": usage.get("reasoning_output_tokens"),
        "token_source": events.get("usage_source"),
        "prompt_sha256": run_meta.get("prompt_sha256"),
        "memory_sha256": run_meta.get("memory_sha256") or None,
        "codex_config_sha256": run_meta.get("config_sha256"),
        "auth_refreshed": run_meta.get("auth_refreshed"),
        "auth_copied_back": run_meta.get("auth_copied_back"),
        "network_egress_isolation_enforced": False,
    }
    out = Path(args.output) if args.output else tdir / "trial-record.json"
    out.write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({k: record[k] for k in ("trial_index", "condition", "valid", "failure_category",
                                             "strict_reward", "cases_passed_of_6")}))
    return 0


# ---------------------------------------------------------------- aggregate
def cmd_aggregate(args: argparse.Namespace) -> int:
    run_dir = Path(args.run_dir)
    records = [json.loads(p.read_text(encoding="utf-8")) for p in sorted(run_dir.glob("trial-*/trial-record.json"))]
    records.sort(key=lambda r: r["trial_index"])
    (run_dir / "trials-summary.json").write_text(
        json.dumps({"job_id": args.job_id, "trial_order": args.trial_order, "trials": records}, indent=2) + "\n",
        encoding="utf-8")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("render-prompt")
    p.add_argument("--template", required=True)
    p.add_argument("--instruction", required=True)
    p.add_argument("--output", required=True)
    p.set_defaults(func=cmd_render_prompt)

    p = sub.add_parser("summarize-events")
    p.add_argument("--events", required=True)
    p.add_argument("--output", required=True)
    p.set_defaults(func=cmd_summarize_events)

    p = sub.add_parser("trial-record")
    p.add_argument("--trial-dir", required=True)
    p.add_argument("--grade-dir", required=True)
    p.add_argument("--job-dir", required=True)
    p.add_argument("--job-id", required=True)
    p.add_argument("--index", type=int, required=True)
    p.add_argument("--condition", required=True, choices=["A", "B"])
    p.add_argument("--model", required=True)
    p.add_argument("--reasoning", required=True)
    p.add_argument("--harbor-exit", required=True)
    p.add_argument("--agent-timeout-sec", type=float, required=True)
    p.add_argument("--output")
    p.set_defaults(func=cmd_trial_record)

    p = sub.add_parser("aggregate")
    p.add_argument("--run-dir", required=True)
    p.add_argument("--job-id", required=True)
    p.add_argument("--trial-order", required=True)
    p.set_defaults(func=cmd_aggregate)

    args = parser.parse_args()
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
