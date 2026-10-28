#!/usr/bin/env python3
"""Helpers for slurm/run-word2vec-ab-v2.sbatch.

Writes only counts and status fields. It never copies trajectory text, verifier
output, commands, memory text, or workspace contents into the records.

Subcommands:
  check-task      validate a staged task copy and write staged-task-preflight.json
  base-template   build the shared base prompt header from staged metadata
  trial-record    write one sanitized trial-record.json
  aggregate       write trials-summary.json and trials-summary.csv for a job
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import sys
import tomllib
from datetime import datetime
from pathlib import Path

ANSI = re.compile(r"\x1b\[[0-9;]*[A-Za-z]")
SUMMARY = re.compile(r"^=+ (.*?) in [0-9.]+s", re.M)
COUNT = re.compile(r"(\d+) (passed|failed|errors?|skipped|xfailed|xpassed|deselected)")
COLLECTED = re.compile(r"collected (\d+) items?")


def read_json(path: Path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def parse_seconds(start: str | None, end: str | None) -> float | None:
    if not start or not end:
        return None
    fmt = lambda s: datetime.fromisoformat(s.replace("Z", "+00:00"))
    return round((fmt(end) - fmt(start)).total_seconds(), 1)


# ---------------------------------------------------------------- check-task
def cmd_check_task(args: argparse.Namespace) -> int:
    task = tomllib.loads(Path(args.task_toml).read_text(encoding="utf-8"))
    staging = json.loads(Path(args.staging).read_text(encoding="utf-8"))
    verifier = task["verifier"]["environment"]
    if verifier.get("network_mode") != "public":
        raise SystemExit("Apptainer preflight: verifier network_mode must be staged as public")
    if staging.get("network_egress_isolation_enforced") is not False:
        raise SystemExit("Apptainer preflight: missing explicit network-isolation limitation")
    artifacts = task.get("artifacts", [])
    if not artifacts or any(not isinstance(p, str) or not p.startswith("/workspace/") for p in artifacts):
        raise SystemExit(f"Unexpected or missing artifact metadata: {artifacts!r}")
    summary = {
        "task": task["task"]["name"],
        "declared_artifacts": artifacts,
        "verifier_network_mode": verifier["network_mode"],
        "network_egress_isolation_enforced": False,
        "verifier_tests_embedded_in_separate_verifier_image": True,
        "preflight": "passed",
    }
    Path(args.output).write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    return 0


# ------------------------------------------------------------- base-template
def cmd_base_template(args: argparse.Namespace) -> int:
    metadata = json.loads(Path(args.metadata).read_text(encoding="utf-8"))
    artifacts = metadata.get("declared_artifacts", [])
    if not artifacts:
        raise SystemExit("Task metadata declares no output artifacts; refusing to launch an agent run")
    if any(not isinstance(p, str) or not p.startswith("/workspace/") for p in artifacts):
        raise SystemExit(f"Unexpected artifact path(s): {artifacts!r}")
    header = (
        "## Required output artifacts\n\n"
        "The official task metadata declares these files as required outputs. "
        "Create the implementation at each exact path so Harbor can collect it:\n"
        + "".join(f"- `{path}`\n" for path in artifacts)
        + "\n"
    )
    source = Path(args.template).read_text(encoding="utf-8")
    Path(args.output).write_text(header + source, encoding="utf-8")
    return 0


# -------------------------------------------------------------- trial-record
def parse_verifier(path: Path) -> dict:
    if not path.is_file():
        return {"collected": 0, "passed": 0, "failed": 0, "errors": 0, "skipped": 0,
                "parse_note": "verifier output absent"}
    text = ANSI.sub("", path.read_text(encoding="utf-8", errors="replace"))
    counts = {"passed": 0, "failed": 0, "errors": 0, "skipped": 0, "xfailed": 0, "xpassed": 0}
    notes = []
    summaries = SUMMARY.findall(text)
    if summaries:
        for number, kind in COUNT.findall(summaries[-1]):
            key = "errors" if kind.startswith("error") else kind
            counts[key] = counts.get(key, 0) + int(number)
    else:
        notes.append("no pytest summary line")
    collected_matches = COLLECTED.findall(text)
    if collected_matches:
        collected = int(collected_matches[-1])
    elif "Interrupted" in text:
        collected = 0
        notes.append("collection interrupted")
    else:
        collected = counts["passed"] + counts["failed"] + counts["skipped"] + counts["xfailed"] + counts["xpassed"]
        notes.append("collected count inferred from summary")
    return {"collected": collected, "passed": counts["passed"], "failed": counts["failed"],
            "errors": counts["errors"], "skipped": counts["skipped"],
            "parse_note": "; ".join(notes) or None}


def classify_steps(steps: list[dict]) -> dict:
    agent = [s for s in steps if s.get("source") == "agent"]
    edits = tests = terminal = 0
    for step in agent:
        for call in step.get("tool_calls") or []:
            name = call.get("function_name")
            args = call.get("arguments") or {}
            if name == "file_editor" and args.get("command") not in (None, "view"):
                edits += 1
            if name == "terminal":
                terminal += 1
                if re.search(r"\bpytest\b|\bpython3?\b", str(args.get("command", ""))):
                    tests += 1
    last_agent = agent[-1] if agent else None
    return {"agent_steps": len(agent), "file_edit_actions": edits,
            "test_or_python_executions": tests, "terminal_actions": terminal,
            "last_agent_step_has_tool_calls": bool(last_agent and last_agent.get("tool_calls"))}


def count_effort_requests(body_dir: Path, marker: Path, effort: str) -> tuple[int, int]:
    total = matched = 0
    if not body_dir.is_dir() or not marker.exists():
        return total, matched
    for path in body_dir.rglob("*_body.json"):
        if path.stat().st_mtime < marker.stat().st_mtime:
            continue
        total += 1
        try:
            body = json.loads(path.read_text(encoding="utf-8", errors="replace"))
        except (OSError, json.JSONDecodeError):
            continue
        if body.get("reasoning_effort") == effort:
            matched += 1
    return total, matched


def cmd_trial_record(args: argparse.Namespace) -> int:
    trial_dir = Path(args.trial_dir)
    job_dir = Path(args.job_dir)
    harbor_trials = [p for p in sorted(job_dir.glob("*")) if p.is_dir()] if job_dir.is_dir() else []
    harbor_trial = harbor_trials[0] if harbor_trials else None
    result = read_json(harbor_trial / "result.json") if harbor_trial else None
    result = result or {}

    workspace_solution = trial_dir / "workspace" / "solution.py"
    solution_present = workspace_solution.is_file() and workspace_solution.stat().st_size > 0

    manifest = read_json(harbor_trial / "artifacts" / "manifest.json") if harbor_trial else None
    harbor_artifact_status = None
    for entry in manifest or []:
        if entry.get("source") == "/workspace/solution.py":
            harbor_artifact_status = entry.get("status")

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

    traj = read_json(harbor_trial / "agent" / "trajectory.json") if harbor_trial else None
    steps = (traj or {}).get("steps", [])
    step_counts = classify_steps(steps) if steps else {
        "agent_steps": 0, "file_edit_actions": 0, "test_or_python_executions": 0,
        "terminal_actions": 0, "last_agent_step_has_tool_calls": False}

    agent_exec = result.get("agent_execution") or {}
    agent_wall = parse_seconds(agent_exec.get("started_at"), agent_exec.get("finished_at"))
    trial_wall = parse_seconds(result.get("started_at"), result.get("finished_at"))
    exc = result.get("exception_info")
    exc_text = json.dumps(exc).lower() if exc else ""

    if (agent_wall is not None and agent_wall >= args.agent_timeout_sec - 5) or "timeout" in exc_text:
        termination = "timeout"
    elif step_counts["agent_steps"] >= args.max_iterations:
        termination = "max_iterations"
    elif exc:
        termination = "error"
    elif not steps:
        termination = "error"
    elif not step_counts["last_agent_step_has_tool_calls"]:
        termination = "finished"
    else:
        termination = "unknown"

    agent_result = result.get("agent_result") or {}
    final_metrics = (traj or {}).get("final_metrics") or {}
    if agent_result.get("n_input_tokens") is not None:
        tok_in, tok_cached = agent_result.get("n_input_tokens"), agent_result.get("n_cache_tokens")
        tok_out, tok_source = agent_result.get("n_output_tokens"), "harbor_agent_result"
    else:
        # Harbor leaves agent_result empty after an agent timeout; OpenHands' trajectory totals remain.
        tok_in = final_metrics.get("total_prompt_tokens")
        tok_cached = final_metrics.get("total_cached_tokens")
        tok_out = final_metrics.get("total_completion_tokens")
        tok_source = "openhands_trajectory_final_metrics" if tok_in is not None else None
    collected = verifier["collected"]
    total_requests, effort_requests = count_effort_requests(
        Path(args.body_dir), Path(args.marker), args.reasoning_effort)

    record = {
        "schema": "word2vec-ab-v2-trial-record/1",
        "job_id": args.job_id,
        "trial_index": args.index,
        "condition": args.condition,
        "harbor_job_name": args.job_name,
        "harbor_exit_code": int(args.harbor_exit) if str(args.harbor_exit).lstrip("-").isdigit() else args.harbor_exit,
        "artifact_solution_py_present": solution_present,
        "harbor_artifact_status": harbor_artifact_status,
        "verifier_collected": collected,
        "verifier_passed": verifier["passed"],
        "verifier_failed": verifier["failed"],
        "verifier_errors": verifier["errors"],
        "verifier_parse_note": verifier.get("parse_note"),
        "reward": reward,
        "status": "VALID" if collected > 0 else "INVALID",
        "agent_wall_seconds": agent_wall,
        "trial_wall_seconds": trial_wall,
        "termination_reason": termination,
        "model_requests": total_requests,
        "model_requests_with_configured_reasoning_effort": effort_requests,
        "agent_steps": step_counts["agent_steps"],
        "input_tokens": tok_in,
        "cached_input_tokens": tok_cached,
        "output_tokens": tok_out,
        "token_source": tok_source,
        "file_edit_actions": step_counts["file_edit_actions"],
        "test_or_python_executions": step_counts["test_or_python_executions"],
        "terminal_actions": step_counts["terminal_actions"],
        "max_iterations": args.max_iterations,
        "agent_timeout_sec": args.agent_timeout_sec,
        "base_template_sha256": args.base_sha,
        "final_template_sha256": args.final_sha,
        "network_egress_isolation_enforced": False,
    }
    (trial_dir / "trial-record.json").write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({k: record[k] for k in ("trial_index", "condition", "status", "termination_reason",
                                             "verifier_collected", "reward")}))
    return 0


# ----------------------------------------------------------------- aggregate
def cmd_aggregate(args: argparse.Namespace) -> int:
    run_dir = Path(args.run_dir)
    records = []
    for path in sorted(run_dir.glob("trial-*/trial-record.json")):
        records.append(json.loads(path.read_text(encoding="utf-8")))
    records.sort(key=lambda r: r["trial_index"])
    (run_dir / "trials-summary.json").write_text(
        json.dumps({"job_id": args.job_id, "trial_order": args.trial_order, "trials": records}, indent=2) + "\n",
        encoding="utf-8")
    if records:
        fields = list(records[0].keys())
        with (run_dir / "trials-summary.csv").open("w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=fields)
            writer.writeheader()
            writer.writerows(records)
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("check-task")
    p.add_argument("--task-toml", required=True)
    p.add_argument("--staging", required=True)
    p.add_argument("--output", required=True)
    p.set_defaults(func=cmd_check_task)

    p = sub.add_parser("base-template")
    p.add_argument("--metadata", required=True)
    p.add_argument("--template", required=True)
    p.add_argument("--output", required=True)
    p.set_defaults(func=cmd_base_template)

    p = sub.add_parser("trial-record")
    p.add_argument("--trial-dir", required=True)
    p.add_argument("--job-dir", required=True)
    p.add_argument("--job-id", required=True)
    p.add_argument("--job-name", required=True)
    p.add_argument("--index", type=int, required=True)
    p.add_argument("--condition", required=True, choices=["A", "B"])
    p.add_argument("--harbor-exit", required=True)
    p.add_argument("--max-iterations", type=int, required=True)
    p.add_argument("--agent-timeout-sec", type=float, required=True)
    p.add_argument("--reasoning-effort", required=True)
    p.add_argument("--base-sha", required=True)
    p.add_argument("--final-sha", required=True)
    p.add_argument("--body-dir", required=True)
    p.add_argument("--marker", required=True)
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
