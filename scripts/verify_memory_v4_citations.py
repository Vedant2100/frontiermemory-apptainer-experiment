#!/usr/bin/env python3
"""Verify the v4 MEMORY.md against the fixed 14-trajectory selection.

Same corpus, checksum, outcome, and size checks as the v3 verifier (8192-byte limit).
Unlike v3, no Reference recipe section is required and the official free-form
format is accepted: bullets are lines starting with "- ", "* " or "N. ". Citation
lines lacking a valid citation are counted as informational, not failures. Every
citation token that is malformed or unresolved is a failure. Citation occurrences
are counted by the source run's outcome (PASS or FAIL) from its final verifier line.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path


EXPECTED_MANIFEST_SHA256 = "c7d31214ed20af4f14f46c4b9a838ebc9aa35a9491dfbce0fa50f7aa456eedd1"
FAMILY_OUTCOMES = {
    "t0025.json": "PASS",
    "t0418.json": "PASS",
    "t0661.json": "PASS",
    "t0085.json": "FAIL",
    "t0109.json": "FAIL",
    "t0269.json": "FAIL",
    "t0384.json": "FAIL",
    "t0401.json": "FAIL",
    "t0434.json": "FAIL",
    "t0449.json": "FAIL",
    "t0515.json": "FAIL",
    "t0529.json": "FAIL",
    "t0622.json": "FAIL",
    "t0653.json": "FAIL",
}
MEMORY_LIMIT = 8192
STRICT = re.compile(r"inputs/(t\d{4}\.json)#step=(\d+)")
TOKEN = re.compile(r"inputs/[^\s()\[\]\"'<>,;`]*")
VERDICT = re.compile(r"#\s*Verifier result\s*(PASS|FAIL)\b", re.IGNORECASE)
BULLET = re.compile(r"^(?:[-*]|\d+\.)\s+")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--corpus", type=Path, required=True)
    parser.add_argument("--memory", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args()

    manifest_bytes = (args.corpus / "SHA256SUMS").read_bytes()
    manifest_sha = hashlib.sha256(manifest_bytes).hexdigest()
    if manifest_sha != EXPECTED_MANIFEST_SHA256:
        raise SystemExit(f"Unexpected manifest SHA-256: {manifest_sha}")
    checksums = {}
    for line in manifest_bytes.decode("utf-8").splitlines():
        digest, relative = line.strip().split(maxsplit=1)
        checksums[relative.lstrip("*")] = digest

    file_report = {}
    for name, outcome in FAMILY_OUTCOMES.items():
        path = args.corpus / "inputs" / name
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        if checksums.get(f"inputs/{name}") != digest:
            raise SystemExit(f"Checksum mismatch: inputs/{name}")
        trajectory = json.loads(path.read_text(encoding="utf-8"))
        steps = {int(s["step_id"]) for s in trajectory["steps"]}
        verdict = VERDICT.search(str(trajectory["steps"][-1].get("message") or ""))
        recorded = verdict.group(1).upper() if verdict else None
        if recorded != outcome:
            raise SystemExit(f"Outcome mismatch for {name}: recorded {recorded}, expected {outcome}")
        file_report[name] = {"outcome": recorded, "steps": steps}

    raw = args.memory.read_bytes()
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as error:
        raise SystemExit(f"Memory is not UTF-8: {error}")
    size = len(raw)
    if size > MEMORY_LIMIT:
        raise SystemExit(f"Memory is {size} bytes, over the {MEMORY_LIMIT} limit")
    if not text.strip():
        raise SystemExit("Memory is empty")

    lines = text.splitlines()
    bullet_lines = [line for line in lines if BULLET.match(line)]
    nonblank_lines = [line for line in lines if line.strip() and not line.startswith("#")]
    headings = [line for line in lines if line.startswith("#")]

    malformed: list[str] = []
    unresolved: list[str] = []
    outcome_counts = {"PASS": 0, "FAIL": 0}
    unique_refs: set[tuple[str, int]] = set()
    bullets_uncited = 0
    bullets_fail_only = 0
    bullets_pass_only = 0
    bullets_mixed = 0
    total_citations = 0
    lines_uncited = 0
    for line in nonblank_lines:
        if not TOKEN.search(line):
            lines_uncited += 1
    for line in bullet_lines:
        refs = []
        for token in TOKEN.findall(line):
            token = token.rstrip(".:*")
            match = STRICT.fullmatch(token)
            if not match:
                malformed.append(token)
                continue
            name, step = match.group(1), int(match.group(2))
            if name not in file_report or step not in file_report[name]["steps"]:
                unresolved.append(token)
                continue
            refs.append((name, step))
        if not refs:
            bullets_uncited += 1
            continue
        total_citations += len(refs)
        outcomes = {file_report[n]["outcome"] for n, _ in refs}
        if outcomes == {"FAIL"}:
            bullets_fail_only += 1
        elif outcomes == {"PASS"}:
            bullets_pass_only += 1
        else:
            bullets_mixed += 1
        for name, step in refs:
            outcome_counts[file_report[name]["outcome"]] += 1
            unique_refs.add((name, step))
    # Citations outside bullets (headings, plain lines) are counted too.
    all_refs_text = TOKEN.findall(text)
    all_resolved = 0
    for token in all_refs_text:
        match = STRICT.fullmatch(token.rstrip(".:*"))
        if match and match.group(1) in file_report and int(match.group(2)) in file_report[match.group(1)]["steps"]:
            all_resolved += 1

    problems: list[str] = []
    if not bullet_lines:
        problems.append("no bullets")
    if malformed:
        problems.append(f"malformed citation tokens: {len(malformed)}")
    if unresolved:
        problems.append(f"unresolved citations: {len(unresolved)}")

    report = {
        "corpus_manifest_sha256": manifest_sha,
        "memory_file": args.memory.name,
        "memory_bytes": size,
        "memory_sha256": hashlib.sha256(raw).hexdigest(),
        "memory_limit_bytes": MEMORY_LIMIT,
        "family_files": len(FAMILY_OUTCOMES),
        "family_outcomes": {k: v["outcome"] for k, v in file_report.items()},
        "headings": len(headings),
        "bullets": len(bullet_lines),
        "bullets_with_valid_citation": len(bullet_lines) - bullets_uncited,
        "bullets_without_citation_informational": bullets_uncited,
        "nonblank_lines_without_citation_informational": lines_uncited,
        "citation_occurrences_in_bullets": total_citations,
        "citation_tokens_all_lines": len(all_refs_text),
        "citation_tokens_all_lines_resolved": all_resolved,
        "unique_cited_steps": len(unique_refs),
        "citation_occurrences_by_source_outcome": outcome_counts,
        "bullets_citing_only_FAIL_sources": bullets_fail_only,
        "bullets_citing_only_PASS_sources": bullets_pass_only,
        "bullets_citing_mixed_sources": bullets_mixed,
        "malformed_tokens": len(malformed),
        "unresolved_citations": len(unresolved),
        "all_citations_resolved": not malformed and not unresolved,
        "problems": problems,
        "passed": not problems,
    }
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2))
    return 0 if not problems else 1


if __name__ == "__main__":
    raise SystemExit(main())
