#!/usr/bin/env python3
"""Task-specific helpers for scripts/run_codex_ollama_trial.sh (Codex CLI, local Ollama).

Generic over TASK (build-word2vec-pipeline or dapt-intrusion-detection-workflow-learning). Shared
pieces are reused from the word2vec harness and not duplicated here:
  scripts/word2vec_ab_v2_records.py   verifier parsing, failure categories (D5')
  scripts/word2vec_codex_trial.py     summarize-events, aggregate
  scripts/word2vec_codex_ollama_helper.py  seed-memory, probe-check, ollama-audit, run-meta

Writes counts, names, and hashes only. It never copies prompts, model output, memory text,
request bodies, or workspace contents into records.

Subcommands:
  task-meta      read the staged task.toml, check artifact paths, write task metadata JSON
  render-prompt  shared "Required output artifacts" header built from task metadata + instruction.md
  manifest       sha256 list (sha256sum format, sorted) of every regular file under a directory
  trial-record   one sanitized trial-record.json; cases_total is task-specific (6 or 37)
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import tomllib
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from word2vec_ab_v2_records import categorize, parse_verifier, read_json  # noqa: E402

SCHEMA = "codex-ollama-trial-record/1"
USAGE_KEYS = ("input_tokens", "cached_input_tokens", "output_tokens", "reasoning_output_tokens")
TASK_SPECS = {
    # cases_total: verifier cases in the task (word2vec: 6; DAPT: 37, oracle 37/37 in the DAPT oracle check).
    "build-word2vec-pipeline": {"cases_total": 6, "workdir": "/workspace"},
    "dapt-intrusion-detection-workflow-learning": {"cases_total": 37, "workdir": "/root"},
}
ZERO_CASES_CATEGORIES = ("NO_ARTIFACT", "CONTRACT_COLLECTION_ERROR", "COLLECTION_ERROR_OTHER")


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read_text_or_empty(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""


def spec_for(task: str) -> dict:
    if task not in TASK_SPECS:
        raise SystemExit(f"unknown TASK {task!r}")
    return TASK_SPECS[task]


# -------------------------------------------------------------------- task-meta
def cmd_task_meta(args: argparse.Namespace) -> int:
    spec = spec_for(args.task)
    task = tomllib.loads(Path(args.task_toml).read_text(encoding="utf-8"))
    if task["task"]["name"] and args.task not in task["task"]["name"]:
        raise SystemExit(f"task.toml name {task['task']['name']!r} does not match TASK {args.task!r}")
    artifacts = task.get("artifacts", [])
    prefix = spec["workdir"] + "/"
    if not artifacts or any(not isinstance(p, str) or not p.startswith(prefix) for p in artifacts):
        raise SystemExit(f"Unexpected or missing artifact metadata: {artifacts!r}")
    if len(artifacts) != 1:
        raise SystemExit("this runner grades exactly one declared artifact")
    verifier = task["verifier"]["environment"]
    if verifier.get("network_mode") != "public":
        raise SystemExit("staged verifier network_mode must be public (Harbor Singularity rejects no-network)")
    out = {
        "task": args.task,
        "task_name": task["task"]["name"],
        "declared_artifacts": artifacts,
        "artifact_rel": [p[len(prefix):] for p in artifacts],
        "workdir": spec["workdir"],
        "cases_total": spec["cases_total"],
        "agent_timeout_sec": task["agent"]["timeout_sec"],
        "verifier_timeout_sec": task["verifier"]["timeout_sec"],
        "verifier_network_mode_staged": verifier["network_mode"],
        "network_egress_isolation_enforced": False,
    }
    Path(args.output).write_text(json.dumps(out, indent=2) + "\n", encoding="utf-8")
    return 0


# ----------------------------------------------------------------- render-prompt
def cmd_render_prompt(args: argparse.Namespace) -> int:
    meta = json.loads(Path(args.task_meta).read_text(encoding="utf-8"))
    # Same header wording as the word2vec base template (scripts/word2vec_ab_v2_records.py base-template).
    header = (
        "## Required output artifacts\n\n"
        "The official task metadata declares these files as required outputs. "
        "Create the implementation at each exact path so Harbor can collect it:\n"
        + "".join(f"- `{path}`\n" for path in meta["declared_artifacts"])
        + "\n"
    )
    instruction = Path(args.instruction).read_text(encoding="utf-8")
    Path(args.output).write_text(header + instruction, encoding="utf-8")
    print(sha256_file(Path(args.output)))
    return 0


# ---------------------------------------------------------------------- manifest
def cmd_manifest(args: argparse.Namespace) -> int:
    root = Path(args.root)
    rows = []
    for path in root.rglob("*"):
        if path.is_file() and not path.is_symlink():
            rel = path.relative_to(root).as_posix()
            rows.append((rel, sha256_file(path)))
    rows.sort()
    Path(args.output).write_text("".join(f"{sha}  ./{rel}\n" for rel, sha in rows), encoding="utf-8")
    return 0


# ------------------------------------------------------------------ trial-record
def _ctx(ps: dict, model: str):
    for m in ps.get("models") or []:
        if m.get("name") == model or m.get("model") == model:
            return m.get("context_length")
    return None


def cmd_trial_record(args: argparse.Namespace) -> int:
    spec = spec_for(args.task)
    cases_total = spec["cases_total"]
    tdir = Path(args.trial_dir)
    gdir = Path(args.grade_dir)
    job_dir = Path(args.job_dir)
    run_meta = read_json(tdir / "run-meta.json") or {}
    events = read_json(tdir / "events-summary.json") or {}
    audit = read_json(Path(args.audit)) or {}
    ctx_before = read_json(Path(args.ps_before)) or {}
    ctx_after = read_json(Path(args.ps_after)) or {}

    harbor_trials = sorted(p for p in job_dir.glob("*") if p.is_dir()) if job_dir.is_dir() else []
    harbor_trial = harbor_trials[0] if harbor_trials else None
    raw_result = read_json(harbor_trial / "result.json") if harbor_trial else None
    result = raw_result or {}

    artifact = Path(args.artifact_file)
    artifact_exists = artifact.is_file() and artifact.stat().st_size > 0
    artifact_sha = sha256_file(artifact) if artifact_exists else None
    # DAPT: the template is already present, so the artifact counts only if the agent changed it.
    artifact_ok = artifact_exists and (not args.artifact_start_sha or artifact_sha != args.artifact_start_sha)

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
        artifact_present=artifact_ok, agent_steps=items_completed,
        model_requests=turns_started, expect_model=True)
    if category == "CONTRACT_COLLECTION_ERROR" and harbor_trial is not None:
        # A missing attribute is the agent's contract error; any other collection error is COLLECTION_ERROR_OTHER.
        if "AttributeError" not in read_text_or_empty(harbor_trial / "verifier" / "test-stdout.txt"):
            category = "COLLECTION_ERROR_OTHER"
    valid = category != "INVALID_INFRA"
    cases_passed = strict_reward = None
    if valid:
        strict_reward = 1.0 if category == "PASS" else 0.0
        cases_passed = 0 if category in ZERO_CASES_CATEGORIES else min(verifier["passed"], cases_total)

    usage = events.get("usage") or {}
    provider = "local_ollama-responses" if args.provider_variant == "responses-custom-provider" else "ollama-oss-builtin"
    record = {
        "schema": SCHEMA,
        "task": args.task,
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
        "cases_total": cases_total,
        "cases_passed": cases_passed,
        "verifier_collected": verifier["collected"],
        "verifier_passed": verifier["passed"],
        "verifier_failed": verifier["failed"],
        "verifier_errors": verifier["errors"],
        "verifier_collection_error": verifier["collection_error"],
        "verifier_network_mode": "public",
        "artifact_present": artifact_ok,
        "artifact_rel_sha256_start": args.artifact_start_sha or None,
        "artifact_final_sha256": artifact_sha,
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
        "auth_file_present": False,
        "openai_credentials_mounted": False,
        "provider": provider,
        "provider_variant": args.provider_variant,
        "provider_base_url_host": args.base_url_host,
        "codex_model_provider_source": "config.toml" if args.provider_variant == "responses-custom-provider" else "--oss",
        "ollama_model": args.model,
        "ollama_num_ctx_loaded_before": _ctx(ctx_before, args.model),
        "ollama_num_ctx_loaded_after": _ctx(ctx_after, args.model),
        "ollama_effort_audit": audit,
        "temperature_setting": "not settable in Codex 0.157 (no config key); Ollama default used",
        "memory_mode": args.memory_mode,
        "network_egress_isolation_enforced": False,
    }
    if args.task == "build-word2vec-pipeline":
        record["cases_passed_of_6"] = cases_passed  # kept only for word2vec compatibility
    out = Path(args.output) if args.output else tdir / "trial-record.json"
    out.write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({k: record[k] for k in ("trial_index", "condition", "valid", "failure_category",
                                             "strict_reward", "cases_passed", "cases_total",
                                             "verifier_collected")}))
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("task-meta")
    p.add_argument("--task", required=True)
    p.add_argument("--task-toml", required=True)
    p.add_argument("--output", required=True)
    p.set_defaults(func=cmd_task_meta)

    p = sub.add_parser("render-prompt")
    p.add_argument("--task-meta", required=True)
    p.add_argument("--instruction", required=True)
    p.add_argument("--output", required=True)
    p.set_defaults(func=cmd_render_prompt)

    p = sub.add_parser("manifest")
    p.add_argument("--root", required=True)
    p.add_argument("--output", required=True)
    p.set_defaults(func=cmd_manifest)

    p = sub.add_parser("trial-record")
    p.add_argument("--task", required=True)
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
    p.add_argument("--artifact-file", required=True)
    p.add_argument("--artifact-start-sha", default="")
    p.add_argument("--provider-variant", required=True)
    p.add_argument("--base-url-host", required=True)
    p.add_argument("--memory-mode", required=True)
    p.add_argument("--audit", required=True)
    p.add_argument("--ps-before", required=True)
    p.add_argument("--ps-after", required=True)
    p.add_argument("--output")
    p.set_defaults(func=cmd_trial_record)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
