#!/usr/bin/env python3
"""Verify that generated-memory citations resolve to the supplied v1.0 evidence."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path


EXPECTED_MANIFEST_SHA256 = "c7d31214ed20af4f14f46c4b9a838ebc9aa35a9491dfbce0fa50f7aa456eedd1"
REFERENCE = re.compile(r"inputs/(t\d{4}\.json)#step=(\d+)")


def references(text: str) -> set[tuple[str, int]]:
    return {(filename, int(step)) for filename, step in REFERENCE.findall(text)}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--corpus", type=Path, required=True)
    parser.add_argument("--evidence", type=Path, required=True)
    parser.add_argument("--memory", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args()

    manifest = args.corpus / "SHA256SUMS"
    manifest_bytes = manifest.read_bytes()
    manifest_sha = hashlib.sha256(manifest_bytes).hexdigest()
    if manifest_sha != EXPECTED_MANIFEST_SHA256:
        raise ValueError(f"Unexpected v1.0 manifest SHA-256: {manifest_sha}")
    checksums = {}
    for line in manifest_bytes.decode("utf-8").splitlines():
        digest, relative = line.strip().split(maxsplit=1)
        checksums[relative.lstrip("*")] = digest

    evidence = args.evidence.read_text(encoding="utf-8")
    memory = args.memory.read_text(encoding="utf-8")
    allowed = references(evidence)
    cited = references(memory)
    if not allowed:
        raise ValueError("No explicit step citations found in evidence input")
    if not cited:
        raise ValueError("Generated memory has no valid step citations")
    unprovided = sorted(cited - allowed)
    if unprovided:
        raise ValueError(f"Memory cites steps absent from evidence input: {unprovided}")

    bullet_blocks: list[str] = []
    current: list[str] = []
    for line in memory.splitlines():
        if line.startswith("- "):
            if current:
                bullet_blocks.append("\n".join(current))
            current = [line]
        elif current:
            if line.strip():
                current.append(line)
            else:
                bullet_blocks.append("\n".join(current))
                current = []
    if current:
        bullet_blocks.append("\n".join(current))
    if not bullet_blocks:
        raise ValueError("Memory must use cited Markdown bullets")
    uncited_bullets = [block for block in bullet_blocks if not references(block)]
    if uncited_bullets:
        raise ValueError(f"Memory has bullets without evidence citations: {len(uncited_bullets)}")

    source_report = []
    for filename, step_id in sorted(cited):
        relative = f"inputs/{filename}"
        expected = checksums.get(relative)
        if expected is None:
            raise ValueError(f"Cited trajectory is absent from manifest: {relative}")
        path = args.corpus / relative
        actual = hashlib.sha256(path.read_bytes()).hexdigest()
        if actual != expected:
            raise ValueError(f"Cited trajectory checksum mismatch: {relative}")
        trajectory = json.loads(path.read_text(encoding="utf-8"))
        step_ids = {
            int(step["step_id"])
            for step in trajectory.get("steps", [])
            if str(step.get("step_id", "")).isdigit()
        }
        if step_id not in step_ids:
            raise ValueError(f"Cited step does not exist: {relative}#step={step_id}")
        tail = "\n".join(
            str(step.get("message") or "") for step in trajectory.get("steps", [])[-3:]
        )
        final_pass = bool(re.search(r"# Verifier result\s*PASS", tail, re.I))
        if not final_pass:
            raise ValueError(f"Cited trajectory lacks a final PASS marker: {relative}")
        source_report.append(
            {
                "reference": f"{relative}#step={step_id}",
                "trajectory_sha256": actual,
                "step_exists": True,
                "source_final_pass": final_pass,
            }
        )

    report = {
        "corpus": "joint-674-v1.0",
        "manifest_sha256": manifest_sha,
        "evidence_sha256": hashlib.sha256(evidence.encode("utf-8")).hexdigest(),
        "memory_sha256": hashlib.sha256(memory.encode("utf-8")).hexdigest(),
        "evidence_reference_count": len(allowed),
        "memory_reference_count": len(cited),
        "all_memory_references_allowed": True,
        "every_bullet_cited": True,
        "references": source_report,
    }
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
