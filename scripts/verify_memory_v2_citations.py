#!/usr/bin/env python3
"""Verify the family memory v2 file against the fixed 14-trajectory selection.

Checks: corpus manifest and per-file checksums; memory is UTF-8 and within the
byte limit; every bullet has at least one citation; every citation token is well
formed, names one of the 14 files, and points at an existing step; each
citation's source run outcome (PASS or FAIL) is recorded from the file's final
verifier message.
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
MEMORY_LIMIT = 4096
STRICT = re.compile(r"inputs/(t\d{4}\.json)#step=(\d+)")
TOKEN = re.compile(r"inputs/[^\s()\[\]\"'<>,;]*")
VERDICT = re.compile(r"#\s*Verifier result\s*(PASS|FAIL)\b", re.IGNORECASE)


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

    bullets = [line for line in text.splitlines() if line.startswith("- ")]
    if not bullets:
        raise SystemExit("Memory has no bullets")

    problems: list[str] = []
    bullets_uncited = 0
    bullets_fail_only = 0
    total_citations = 0
    malformed = []
    unresolved = []
    outcome_counts = {"PASS": 0, "FAIL": 0}
    unique_refs: set[tuple[str, int]] = set()
    for bullet in bullets:
        tokens = TOKEN.findall(bullet)
        refs = []
        for token in tokens:
            token = token.rstrip(".")
            match = STRICT.fullmatch(token)
            if not match:
                malformed.append(token)
                continue
            name, step = match.group(1), int(match.group(2))
            if name not in file_report:
                unresolved.append(token)
                continue
            if step not in file_report[name]["steps"]:
                unresolved.append(token)
                continue
            refs.append((name, step))
        if not refs:
            bullets_uncited += 1
        total_citations += len(refs)
        for name, step in refs:
            outcome_counts[file_report[name]["outcome"]] += 1
            unique_refs.add((name, step))
        if refs and all(file_report[n]["outcome"] == "FAIL" for n, _ in refs):
            bullets_fail_only += 1

    if malformed:
        problems.append(f"malformed citation tokens: {len(malformed)}")
    if unresolved:
        problems.append(f"unresolved citations: {len(unresolved)}")
    if bullets_uncited:
        problems.append(f"bullets without a valid citation: {bullets_uncited}")

    report = {
        "corpus_manifest_sha256": manifest_sha,
        "memory_file": args.memory.name,
        "memory_bytes": size,
        "memory_sha256": hashlib.sha256(raw).hexdigest(),
        "memory_limit_bytes": MEMORY_LIMIT,
        "family_files": len(FAMILY_OUTCOMES),
        "family_outcomes": {k: v["outcome"] for k, v in file_report.items()},
        "bullets": len(bullets),
        "bullets_without_valid_citation": bullets_uncited,
        "citation_occurrences": total_citations,
        "unique_cited_steps": len(unique_refs),
        "citation_occurrences_by_source_outcome": outcome_counts,
        "bullets_citing_only_FAIL_sources": bullets_fail_only,
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
