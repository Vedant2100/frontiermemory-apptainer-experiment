#!/usr/bin/env python3
"""Assess whether Harbor's OpenCode run made a substantive source-code edit."""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path


SOURCE_SUFFIXES = {".ts", ".tsx", ".js", ".jsx", ".mjs", ".cjs"}
TEST_COMMAND = re.compile(
    r"\b(test|tests|jest|vitest|mocha|ava|tap|tsc|typecheck|lint)\b|"
    r"\b(npm|pnpm|yarn)\s+(run|test|exec)\b",
    re.IGNORECASE,
)


def latest_trial_dir(jobs_dir: Path, job_name: str) -> Path | None:
    matches = [path for path in (jobs_dir / job_name).glob("*") if path.is_dir()]
    if not matches:
        return None
    return max(matches, key=lambda path: path.stat().st_mtime)


def changed_source_stats(patch_path: Path) -> tuple[list[str], int, int]:
    changed_files: list[str] = []
    additions = deletions = 0
    current_is_source = False
    for line in patch_path.read_text(errors="replace").splitlines():
        if line.startswith("+++ b/"):
            current = line[6:]
            path = Path(current)
            normalized = current.lower()
            current_is_source = (
                path.suffix.lower() in SOURCE_SUFFIXES
                and not any(part in normalized for part in ("/test", ".test.", ".spec."))
            )
            if current_is_source and current not in changed_files:
                changed_files.append(current)
        elif current_is_source and line.startswith("+") and not line.startswith("+++"):
            additions += 1
        elif current_is_source and line.startswith("-") and not line.startswith("---"):
            deletions += 1
    return changed_files, additions, deletions


def attempted_tests(opencode_path: Path) -> list[str]:
    if not opencode_path.exists():
        return []
    found: list[str] = []
    for line in opencode_path.read_text(errors="replace").splitlines():
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        if event.get("type") != "tool_use":
            continue
        part = event.get("part") or {}
        if str(part.get("tool", "")).lower() not in {"bash", "shell"}:
            continue
        call_input = ((part.get("state") or {}).get("input") or {})
        command = call_input.get("command") or call_input.get("cmd")
        if isinstance(command, str) and TEST_COMMAND.search(command):
            found.append(" ".join(command.split()))
    return found


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--jobs-dir", type=Path, required=True)
    parser.add_argument("--job-name", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    trial_dir = latest_trial_dir(args.jobs_dir, args.job_name)
    patch_path = None
    if trial_dir:
        for candidate in (
            trial_dir / "artifacts/logs/artifacts/model.patch",
            trial_dir / "artifacts/model.patch",
        ):
            if candidate.exists():
                patch_path = candidate
                break
    opencode_path = trial_dir / "agent/opencode.txt" if trial_dir else None
    source_files: list[str] = []
    additions = deletions = 0
    if patch_path and patch_path.exists():
        source_files, additions, deletions = changed_source_stats(patch_path)
    tests = attempted_tests(opencode_path) if opencode_path else []
    changed_lines = additions + deletions
    progress = bool(source_files and changed_lines >= 10)
    result = {
        "assessment": "real-source-implementation-progress" if progress else "no-substantive-source-progress",
        "progress": progress,
        "trial_dir": str(trial_dir) if trial_dir else None,
        "patch_path": str(patch_path) if patch_path and patch_path.exists() else None,
        "source_files_changed": source_files,
        "source_additions": additions,
        "source_deletions": deletions,
        "tests_attempted": tests,
        "test_attempt_count": len(tests),
        "basis": "A B run is allowed only after at least ten changed lines in non-test TypeScript/JavaScript source files.",
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
