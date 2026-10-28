#!/usr/bin/env python3
"""Build condensed, step-numbered evidence for the fixed 14-trajectory family set.

CPU-only and deterministic. Reads only the pinned joint-674-v1.0 corpus. The
selection is fixed by results/word2vec-openhands/protocol-v2.md (D2) and is not
derived from the target task. Outputs contain trajectory text and must stay in a
git-ignored job directory.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path


# Fixed selection (protocol-v2 D2). Do not change without a new protocol revision.
FAMILY_OUTCOMES = {
    "t0025": "PASS",
    "t0418": "PASS",
    "t0661": "PASS",
    "t0085": "FAIL",
    "t0109": "FAIL",
    "t0269": "FAIL",
    "t0384": "FAIL",
    "t0401": "FAIL",
    "t0434": "FAIL",
    "t0449": "FAIL",
    "t0515": "FAIL",
    "t0529": "FAIL",
    "t0622": "FAIL",
    "t0653": "FAIL",
}
EXPECTED_MANIFEST_SHA256 = "c7d31214ed20af4f14f46c4b9a838ebc9aa35a9491dfbce0fa50f7aa456eedd1"
VERDICT = re.compile(r"#\s*Verifier result\s*(PASS|FAIL)\b", re.IGNORECASE)

MESSAGE_CHARS = 600
TOOL_ARG_CHARS = 400
OBSERVATION_CHARS = 400
INSTRUCTION_CHARS = 3000
BLOCK_CHARS = 8000
FILE_CAP_CHARS = 40000


def truncate(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    return text[:limit] + f" ...[+{len(text) - limit} chars]"


def observation_text(observation: object) -> str:
    if observation is None:
        return ""
    if isinstance(observation, dict) and isinstance(observation.get("results"), list):
        parts = []
        for result in observation["results"]:
            if isinstance(result, dict):
                content = result.get("content")
                parts.append(content if isinstance(content, str) else json.dumps(content, ensure_ascii=False))
        return "\n".join(parts)
    if isinstance(observation, str):
        return observation
    return json.dumps(observation, ensure_ascii=False, sort_keys=True)


def render_step(step: dict, instruction_step: int | None) -> str:
    step_id = step.get("step_id")
    lines = [f"--- step={step_id} source={step.get('source')}"]
    message = str(step.get("message") or "")
    if step_id == instruction_step:
        lines.append("message: (initial instruction; shown in the header)")
    elif message.strip():
        lines.append("message: " + truncate(message.strip(), MESSAGE_CHARS))
    for call in step.get("tool_calls") or []:
        name = call.get("function_name") or call.get("name") or "?"
        args = json.dumps(call.get("arguments"), ensure_ascii=False, sort_keys=True)
        lines.append(f"tool_call: {name} {truncate(args, TOOL_ARG_CHARS)}")
    observation = observation_text(step.get("observation"))
    if observation.strip():
        lines.append("observation: " + truncate(observation.strip(), OBSERVATION_CHARS))
    block = "\n".join(lines)
    return truncate(block, BLOCK_CHARS)


def condense(path: Path, file_name: str, outcome: str) -> tuple[str, dict]:
    trajectory = json.loads(path.read_text(encoding="utf-8"))
    steps = trajectory.get("steps", [])
    if not steps:
        raise ValueError(f"{file_name} has no steps")
    step_ids = [int(step["step_id"]) for step in steps]
    if step_ids != list(range(1, len(steps) + 1)):
        raise ValueError(f"{file_name} step ids are not 1..N: {step_ids[:5]}...")

    last_message = str(steps[-1].get("message") or "")
    verdict = VERDICT.search(last_message)
    if not verdict or verdict.group(1).upper() != outcome:
        raise ValueError(f"{file_name} final verifier message does not match expected {outcome}")

    instruction_step = next((s for s in steps if s.get("source") == "user"), steps[0])
    instruction_id = int(instruction_step["step_id"])
    instruction = truncate(str(instruction_step.get("message") or "").strip(), INSTRUCTION_CHARS)

    header = (
        f"FILE: inputs/{file_name}\n"
        f"RECORDED OUTCOME: {outcome}\n"
        f"TOTAL STEPS: {len(steps)}\n"
        f"INITIAL INSTRUCTION (step={instruction_id}, source={instruction_step.get('source')}):\n"
        f"{instruction}\n\n"
        "STEPS:\n"
    )
    blocks = [render_step(step, instruction_id) for step in steps]
    body_total = sum(len(block) + 2 for block in blocks)
    omitted: list[int] = []
    truncated = False

    if len(header) + body_total > FILE_CAP_CHARS:
        truncated = True
        note_budget = 200
        budget = FILE_CAP_CHARS - len(header) - note_budget
        head_budget = budget // 2
        head_count = 0
        used = 0
        for block in blocks:
            if used + len(block) + 2 > head_budget:
                break
            used += len(block) + 2
            head_count += 1
        tail_indices: list[int] = []
        tail_used = 0
        for index in range(len(blocks) - 1, head_count - 1, -1):
            if tail_used + len(blocks[index]) + 2 > budget - used:
                break
            tail_indices.append(index)
            tail_used += len(blocks[index]) + 2
        tail_indices.reverse()
        kept = set(range(head_count)) | set(tail_indices)
        omitted = [i + 1 for i in range(len(blocks)) if i not in kept]
        parts = []
        for index, block in enumerate(blocks):
            if index == head_count and omitted:
                parts.append(
                    f"[TRUNCATED: steps {omitted[0]}-{omitted[-1]} omitted "
                    f"({len(omitted)} steps) to fit the evidence size cap]"
                )
            if index in kept:
                parts.append(block)
        body = "\n\n".join(parts)
    else:
        body = "\n\n".join(blocks)

    text = header + body + "\n"
    meta = {
        "file": f"inputs/{file_name}",
        "id": file_name.removesuffix(".json"),
        "outcome": outcome,
        "total_steps": len(steps),
        "steps": step_ids,
        "instruction_step": instruction_id,
        "evidence_chars": len(text),
        "truncated": truncated,
        "omitted_steps": omitted,
    }
    return text, meta


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--corpus", type=Path, required=True)
    parser.add_argument("--out-dir", type=Path, required=True)
    args = parser.parse_args()

    manifest_bytes = (args.corpus / "SHA256SUMS").read_bytes()
    manifest_sha = hashlib.sha256(manifest_bytes).hexdigest()
    if manifest_sha != EXPECTED_MANIFEST_SHA256:
        raise SystemExit(f"Unexpected corpus manifest SHA-256: {manifest_sha}")
    checksums = {}
    for line in manifest_bytes.decode("utf-8").splitlines():
        digest, relative = line.strip().split(maxsplit=1)
        checksums[relative.lstrip("*")] = digest

    evidence_dir = args.out_dir / "evidence"
    evidence_dir.mkdir(parents=True, exist_ok=True)
    files = []
    for file_id in sorted(FAMILY_OUTCOMES):
        file_name = f"{file_id}.json"
        path = args.corpus / "inputs" / file_name
        relative = f"inputs/{file_name}"
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        if checksums.get(relative) != digest:
            raise SystemExit(f"Checksum mismatch against SHA256SUMS: {relative}")
        text, meta = condense(path, file_name, FAMILY_OUTCOMES[file_id])
        evidence_path = evidence_dir / f"{file_id}.txt"
        evidence_path.write_text(text, encoding="utf-8")
        meta["sha256"] = digest
        meta["evidence_file"] = f"evidence/{file_id}.txt"
        files.append(meta)

    index = {
        "corpus_manifest_sha256": manifest_sha,
        "selection": "protocol-v2 D2 family set (14 files, 3 PASS, 11 FAIL)",
        "caps": {
            "message_chars": MESSAGE_CHARS,
            "tool_arg_chars": TOOL_ARG_CHARS,
            "observation_chars": OBSERVATION_CHARS,
            "file_cap_chars": FILE_CAP_CHARS,
        },
        "files": files,
    }
    (args.out_dir / "evidence-index.json").write_text(json.dumps(index, indent=2) + "\n", encoding="utf-8")
    summary = {
        "files": len(files),
        "pass": sum(1 for f in files if f["outcome"] == "PASS"),
        "fail": sum(1 for f in files if f["outcome"] == "FAIL"),
        "truncated": [f["id"] for f in files if f["truncated"]],
        "max_evidence_chars": max(f["evidence_chars"] for f in files),
    }
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
