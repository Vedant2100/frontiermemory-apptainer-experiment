#!/usr/bin/env python3
"""Watch Harbor's live OpenCode event file and stop repeated shell loops."""

from __future__ import annotations

import argparse
import json
import os
import signal
import sys
import time
from collections import Counter
from pathlib import Path


def find_event_file(jobs_dir: Path, job_name: str) -> Path | None:
    matches = list(jobs_dir.glob(f"{job_name}/**/agent/opencode.txt"))
    if not matches:
        return None
    return max(matches, key=lambda path: path.stat().st_mtime)


def parse_shell_calls(path: Path) -> list[tuple[str, str]]:
    calls: list[tuple[str, str]] = []
    try:
        lines = path.read_text(errors="replace").splitlines()
    except OSError:
        return calls

    for line in lines:
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        if event.get("type") != "tool_use":
            continue
        part = event.get("part") or {}
        if str(part.get("tool", "")).lower() not in {"bash", "shell"}:
            continue
        state = part.get("state") or {}
        call_input = state.get("input") or {}
        command = call_input.get("command") or call_input.get("cmd")
        if not isinstance(command, str) or not command.strip():
            continue
        output = state.get("output")
        if output is None:
            output = (state.get("metadata") or {}).get("output", "")
        calls.append((" ".join(command.split()), str(output)))
    return calls


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--jobs-dir", type=Path, required=True)
    parser.add_argument("--job-name", required=True)
    parser.add_argument("--harbor-pid", type=int, required=True)
    parser.add_argument("--marker", type=Path, required=True)
    parser.add_argument("--interval", type=float, default=15.0)
    args = parser.parse_args()

    seen_file: Path | None = None
    previous_count = 0
    while True:
        try:
            os.kill(args.harbor_pid, 0)
        except OSError:
            return 0

        event_file = find_event_file(args.jobs_dir, args.job_name)
        if event_file is not None:
            calls = parse_shell_calls(event_file)
            if event_file != seen_file or len(calls) != previous_count:
                print(
                    f"{time.strftime('%Y-%m-%dT%H:%M:%S%z')} "
                    f"events={event_file} shell_calls={len(calls)}",
                    flush=True,
                )
                seen_file = event_file
                previous_count = len(calls)

            recent = calls[-10:]
            command_counts = Counter(command for command, _ in recent)
            for command, count in command_counts.items():
                if count < 4:
                    continue
                outputs = [output for candidate, output in recent if candidate == command]
                if len(set(outputs)) != 1:
                    continue
                reason = {
                    "reason": "same shell command and output repeated at least four times in the last ten shell calls",
                    "command": command,
                    "repetitions": count,
                    "event_file": str(event_file),
                    "observed_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
                }
                args.marker.parent.mkdir(parents=True, exist_ok=True)
                args.marker.write_text(json.dumps(reason, indent=2) + "\n")
                print(json.dumps(reason), flush=True)
                try:
                    os.kill(args.harbor_pid, signal.SIGINT)
                    time.sleep(20)
                    os.kill(args.harbor_pid, 0)
                except OSError:
                    return 0
                try:
                    os.kill(args.harbor_pid, signal.SIGTERM)
                except OSError:
                    pass
                return 0
        time.sleep(args.interval)


if __name__ == "__main__":
    sys.exit(main())
