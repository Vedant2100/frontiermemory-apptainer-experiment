#!/usr/bin/env python3
"""Stop repeated OpenCode tool loops while leaving Harbor to verify the work."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import signal
import sys
import time
from pathlib import Path
from typing import Any


def find_event_file(jobs_dir: Path, job_name: str) -> Path | None:
    matches = list(jobs_dir.glob(f"{job_name}/**/agent/opencode.txt"))
    return max(matches, key=lambda path: path.stat().st_mtime) if matches else None


def parse_event(line: str) -> dict[str, Any] | None:
    try:
        event = json.loads(line)
    except json.JSONDecodeError:
        return None
    if event.get("type") != "tool_use":
        return None
    part = event.get("part") or {}
    tool = str(part.get("tool", "")).lower()
    if not tool:
        return None
    state = part.get("state") or {}
    call_input = state.get("input") or {}
    output = state.get("output")
    if output is None:
        output = (state.get("metadata") or {}).get("output", "")
    return {
        "tool": tool,
        "input": call_input,
        "status": state.get("status", ""),
        "output": str(output),
        "error": str(state.get("error") or ""),
    }


def parse_tool_calls(path: Path) -> list[dict[str, Any]]:
    try:
        lines = path.read_text(errors="replace").splitlines()
    except OSError:
        return []
    calls = []
    for line in lines:
        call = parse_event(line)
        if call is not None:
            calls.append(call)
    return calls


def is_progress_call(call: dict[str, Any]) -> bool:
    if call["status"] not in {"completed", "success"}:
        return False
    tool = call["tool"]
    if tool in {"edit", "write", "apply_patch"}:
        return True
    if tool not in {"bash", "shell"}:
        return False
    command = str((call["input"] or {}).get("command") or "")
    test_command = re.search(
        r"\b(pytest|unittest|tox|nox|npm\s+test|pnpm\s+test|yarn\s+test|go\s+test|cargo\s+test|mvn\s+test|gradle\s+test)\b",
        command,
    )
    write_command = re.search(
        r"(?:\b(?:cat|tee|printf)\b[^\n]{0,500}(?:>>?|\btee\s+\S+)|"
        r"\b(?:touch|cp|mv|patch)\b|"
        r"\b(?:sed|perl)\s+-i\b|\bwrite_text\s*\(|\bopen\([^\n]{0,120},\s*['\"]w)",
        command,
    )
    return bool(test_command or write_command)


def reason_for_unproductive_steps(path: Path, step_limit: int) -> dict[str, Any] | None:
    try:
        lines = path.read_text(errors="replace").splitlines()
    except OSError:
        return None
    events = []
    for line in lines:
        if not line.strip():
            continue
        try:
            events.append(json.loads(line))
        except json.JSONDecodeError:
            continue

    no_progress_steps = 0
    step_had_progress = False
    for event in events:
        event_type = event.get("type")
        part = event.get("part") or {}
        if event_type == "step_start":
            step_had_progress = False
        elif event_type == "tool_use":
            call = parse_event(json.dumps(event))
            if call and is_progress_call(call):
                step_had_progress = True
        elif event_type == "step_finish":
            if step_had_progress:
                no_progress_steps = 0
            else:
                no_progress_steps += 1
                if part.get("reason") == "length":
                    return {
                        "reason": "an assistant turn exhausted its output limit without a code edit or test",
                        "no_progress_steps": no_progress_steps,
                    }
                if no_progress_steps >= step_limit:
                    return {
                        "reason": "too many consecutive assistant turns ended without a code edit or test",
                        "no_progress_steps": no_progress_steps,
                    }
            step_had_progress = False
    return None


def reason_for_repeated_operation(calls: list[dict[str, Any]]) -> dict[str, Any] | None:
    eligible = {"bash", "shell", "read", "grep"}
    recent = [call for call in calls[-10:] if call["tool"] in eligible]
    counts: dict[str, tuple[dict[str, Any], int]] = {}
    for call in recent:
        tool_input = call["input"] or {}
        if call["tool"] in {"bash", "shell"}:
            command = " ".join(
                str(tool_input.get("command") or tool_input.get("cmd") or "").split()
            )
            normalized_input: Any = {"command": command}
        else:
            normalized_input = tool_input
        signature = json.dumps(
            [call["tool"], normalized_input, call["output"]],
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        )
        previous = counts.get(signature)
        counts[signature] = (call, (previous[1] if previous else 0) + 1)
    for signature, (call, count) in counts.items():
        if count >= 4:
            return {
                "reason": "same shell, read, or search operation and output repeated at least four times in the last ten calls",
                "tool": call["tool"],
                "operation_hash": hashlib.sha256(signature.encode()).hexdigest()[:12],
                "repetitions": count,
            }
    return None


def reason_for_repeated_tool_error(calls: list[dict[str, Any]]) -> dict[str, Any] | None:
    recent_errors = [call for call in calls[-8:] if call["status"] == "error"]
    counts: dict[str, tuple[dict[str, Any], int]] = {}
    for call in recent_errors:
        signature = json.dumps([call["error"]], separators=(",", ":"))
        previous = counts.get(signature)
        counts[signature] = (call, (previous[1] if previous else 0) + 1)
    for signature, (call, count) in counts.items():
        if count >= 3:
            return {
                "reason": "the same tool error occurred at least three times in the last eight calls",
                "tool": call["tool"],
                "operation_hash": hashlib.sha256(signature.encode()).hexdigest()[:12],
                "repetitions": count,
            }
    return None


def reason_for_repeated_edit_failure(calls: list[dict[str, Any]]) -> dict[str, Any] | None:
    edits = [call for call in calls if call["tool"] in {"edit", "apply_patch"}][-8:]
    failed = [call for call in edits if call["status"] == "error"]
    counts: dict[str, tuple[dict[str, Any], int]] = {}
    for call in failed:
        signature = json.dumps(
            [call["tool"], (call["input"] or {}).get("filePath"), call["error"]],
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        )
        previous = counts.get(signature)
        counts[signature] = (call, (previous[1] if previous else 0) + 1)
    for signature, (call, count) in counts.items():
        if count >= 3:
            return {
                "reason": "the same edit operation failed at least three times in the last eight edit attempts",
                "tool": call["tool"],
                "operation_hash": hashlib.sha256(signature.encode()).hexdigest()[:12],
                "repetitions": count,
            }
    return None


def proc_record(pid: int) -> tuple[int, str, list[str]] | None:
    try:
        raw_stat = Path(f"/proc/{pid}/stat").read_text()
        end_of_comm = raw_stat.rfind(")")
        fields = raw_stat[end_of_comm + 2 :].split()
        state = fields[0]
        parent_pid = int(fields[1])
        argv = [
            item.decode(errors="replace")
            for item in Path(f"/proc/{pid}/cmdline").read_bytes().split(b"\0")
            if item
        ]
    except (OSError, IndexError, ValueError):
        return None
    return parent_pid, state, argv


def is_opencode_command(argv: list[str]) -> bool:
    if not argv:
        return False
    executable = Path(argv[0]).name
    if executable == "opencode":
        return True
    is_node = executable in {"node", "nodejs"}
    return is_node and any(
        Path(arg).name in {"opencode", "opencode.mjs"} for arg in argv[1:3]
    )


def find_opencode_pid(harbor_pid: int) -> int | None:
    records: dict[int, tuple[int, str, list[str]]] = {}
    for stat_path in Path("/proc").glob("[0-9]*/stat"):
        try:
            pid = int(stat_path.parent.name)
        except ValueError:
            continue
        record = proc_record(pid)
        if record is not None:
            records[pid] = record

    children: dict[int, list[int]] = {}
    for pid, (parent_pid, _, _) in records.items():
        children.setdefault(parent_pid, []).append(pid)
    pending = list(children.get(harbor_pid, []))
    descendants = []
    while pending:
        pid = pending.pop()
        descendants.append(pid)
        pending.extend(children.get(pid, []))

    for pid in reversed(descendants):
        if is_opencode_command(records[pid][2]):
            return pid
    return None


def interrupt_process(pid: int, sig: signal.Signals, timeout: float) -> bool:
    try:
        os.kill(pid, sig)
    except OSError:
        return True
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        record = proc_record(pid)
        if record is None or record[1] == "Z":
            return True
        time.sleep(0.25)
    record = proc_record(pid)
    return record is None or record[1] == "Z"


def stop_opencode(harbor_pid: int) -> bool:
    opencode_pid = find_opencode_pid(harbor_pid)
    if opencode_pid is None:
        return False
    if interrupt_process(opencode_pid, signal.SIGINT, 20):
        return True
    if interrupt_process(opencode_pid, signal.SIGTERM, 5):
        return True
    return interrupt_process(opencode_pid, signal.SIGKILL, 1)


def stop_reason(
    calls: list[dict[str, Any]], event_file: Path, no_progress_steps: int
) -> dict[str, Any] | None:
    detectors = (
        reason_for_repeated_operation,
        reason_for_repeated_tool_error,
        reason_for_repeated_edit_failure,
    )
    for detector in detectors:
        reason = detector(calls)
        if reason is not None:
            return reason
    return reason_for_unproductive_steps(event_file, no_progress_steps)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--jobs-dir", type=Path, required=True)
    parser.add_argument("--job-name", required=True)
    parser.add_argument("--harbor-pid", type=int, required=True)
    parser.add_argument("--marker", type=Path, required=True)
    parser.add_argument("--interval", type=float, default=15.0)
    parser.add_argument("--no-progress-steps", type=int, default=8)
    args = parser.parse_args()

    previous_count = 0
    while True:
        harbor = proc_record(args.harbor_pid)
        if harbor is None or harbor[1] == "Z":
            return 0
        event_file = find_event_file(args.jobs_dir, args.job_name)
        if event_file is not None:
            calls = parse_tool_calls(event_file)
            if len(calls) != previous_count:
                print(
                    f"{time.strftime('%Y-%m-%dT%H:%M:%S%z')} "
                    f"events={event_file} tool_calls={len(calls)}",
                    flush=True,
                )
                previous_count = len(calls)
            reason = stop_reason(calls, event_file, args.no_progress_steps)
            if reason is not None:
                reason.update(
                    event_file=str(event_file),
                    observed_at=time.strftime("%Y-%m-%dT%H:%M:%S%z"),
                    opencode_interrupted=stop_opencode(args.harbor_pid),
                )
                args.marker.parent.mkdir(parents=True, exist_ok=True)
                args.marker.write_text(json.dumps(reason, indent=2) + "\n")
                print(json.dumps(reason), flush=True)
                return 0
        time.sleep(args.interval)


if __name__ == "__main__":
    sys.exit(main())
