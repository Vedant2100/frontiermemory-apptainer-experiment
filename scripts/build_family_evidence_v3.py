#!/usr/bin/env python3
"""Build condensed, step-numbered evidence for the fixed 14-trajectory family set (v3).

CPU-only and deterministic. Reads only the pinned joint-674-v1.0 corpus. The
selection is the protocol-v2 D2 family set (unchanged from v2). Unlike v2, this
version does not truncate messages or tool-call arguments per step. Only
observations are capped (head + tail, 4,000 chars), reasoning_content is never
rendered, and each whole condensed trajectory is capped at 120,000 characters by
dropping a contiguous middle range of steps. Step ids keep the verifier numbering.
Outputs contain trajectory text and must stay in a git-ignored job directory.
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

OBSERVATION_CAP_CHARS = 4000
OBSERVATION_HEAD_CHARS = 2000
OBSERVATION_TAIL_CHARS = 2000
TRAJECTORY_CAP_CHARS = 120000
NOTE_BUDGET_CHARS = 300


def cap_observation(text: str) -> tuple[str, bool]:
    """Keep the first and last 2,000 chars of an observation longer than 4,000 chars."""
    if len(text) <= OBSERVATION_CAP_CHARS:
        return text, False
    dropped = len(text) - OBSERVATION_HEAD_CHARS - OBSERVATION_TAIL_CHARS
    marker = f"\n...[observation middle omitted: {dropped} chars]...\n"
    return text[:OBSERVATION_HEAD_CHARS] + marker + text[-OBSERVATION_TAIL_CHARS:], True


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


def render_tool_call(call: dict) -> str:
    """Render arguments without truncation. String arguments (code, commands) are kept verbatim."""
    name = call.get("function_name") or call.get("name") or "?"
    arguments = call.get("arguments")
    if isinstance(arguments, dict):
        lines = [f"tool_call: {name}"]
        for key, value in arguments.items():
            if isinstance(value, str):
                lines.append(f"  arg {key} (verbatim text):")
                lines.append(value)
            else:
                lines.append(f"  arg {key} (json): " + json.dumps(value, ensure_ascii=False, sort_keys=True))
        return "\n".join(lines)
    return f"tool_call: {name} (json): " + json.dumps(arguments, ensure_ascii=False, sort_keys=True)


def render_step(step: dict, instruction_step: int) -> tuple[str, bool]:
    step_id = step.get("step_id")
    lines = [f"--- step={step_id} source={step.get('source')}"]
    message = str(step.get("message") or "").strip()
    if step_id == instruction_step:
        lines.append("message: (initial instruction; shown in the header)")
    elif message:
        lines.append("message: " + message)
    for call in step.get("tool_calls") or []:
        lines.append(render_tool_call(call))
    observation, capped = cap_observation(observation_text(step.get("observation")).strip())
    if observation:
        lines.append("observation: " + observation)
    # reasoning_content is intentionally never read or rendered.
    return "\n".join(lines), capped


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
    instruction = str(instruction_step.get("message") or "").strip()

    header = (
        f"FILE: inputs/{file_name}\n"
        f"RECORDED OUTCOME: {outcome}\n"
        f"TOTAL STEPS: {len(steps)}\n"
        f"INITIAL INSTRUCTION (step={instruction_id}, source={instruction_step.get('source')}):\n"
        f"{instruction}\n\n"
        "STEPS:\n"
    )
    rendered = [render_step(step, instruction_id) for step in steps]
    blocks = [block for block, _ in rendered]
    observations_capped = sum(1 for _, capped in rendered if capped)
    full_text = header + "\n\n".join(blocks) + "\n"
    omitted: list[int] = []
    truncated = False

    if len(full_text) > TRAJECTORY_CAP_CHARS:
        truncated = True
        budget = TRAJECTORY_CAP_CHARS - len(header) - NOTE_BUDGET_CHARS - 1
        head_budget = budget // 2
        head_count, used = 0, 0
        for block in blocks:
            if used + len(block) + 2 > head_budget:
                break
            used += len(block) + 2
            head_count += 1
        tail_indices: list[int] = []
        tail_used = 0
        for index in range(len(blocks) - 1, head_count - 1, -1):
            if used + tail_used + len(blocks[index]) + 2 > budget:
                break
            tail_indices.append(index)
            tail_used += len(blocks[index]) + 2
        tail_indices.reverse()
        kept = set(range(head_count)) | set(tail_indices)
        omitted = [i + 1 for i in range(len(blocks)) if i not in kept]
        marker = (
            f"[TRUNCATED: steps {omitted[0]}-{omitted[-1]} omitted ({len(omitted)} steps) "
            f"to fit the {TRAJECTORY_CAP_CHARS}-char trajectory cap]"
        ) if omitted else ""
        parts = []
        previous_kept = True
        for index, block in enumerate(blocks):
            if index in kept:
                if not previous_kept:
                    parts.append(marker)
                parts.append(block)
                previous_kept = True
            else:
                previous_kept = False
        if not previous_kept:
            parts.append(marker)
        text = header + "\n\n".join(parts) + "\n"
    else:
        text = full_text

    if len(text) > TRAJECTORY_CAP_CHARS:
        raise ValueError(f"{file_name} evidence {len(text)} chars exceeds the cap")
    reasoning_steps = sum(1 for s in steps if s.get("reasoning_content"))
    meta = {
        "file": f"inputs/{file_name}",
        "id": file_name.removesuffix(".json"),
        "outcome": outcome,
        "total_steps": len(steps),
        "steps": step_ids,
        "instruction_step": instruction_id,
        "evidence_chars": len(text),
        "uncapped_chars": len(full_text),
        "truncated": truncated,
        "omitted_steps": omitted,
        "observations_capped": observations_capped,
        "reasoning_content_steps_dropped": reasoning_steps,
        "longest_step_block_chars": max(len(b) for b in blocks),
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
        (evidence_dir / f"{file_id}.txt").write_text(text, encoding="utf-8")
        meta["sha256"] = digest
        meta["evidence_file"] = f"evidence/{file_id}.txt"
        files.append(meta)

    index = {
        "corpus_manifest_sha256": manifest_sha,
        "selection": "protocol-v2 D2 family set (14 files, 3 PASS, 11 FAIL)",
        "caps": {
            "message_chars": None,
            "tool_arg_chars": None,
            "observation_cap_chars": OBSERVATION_CAP_CHARS,
            "observation_head_chars": OBSERVATION_HEAD_CHARS,
            "observation_tail_chars": OBSERVATION_TAIL_CHARS,
            "trajectory_cap_chars": TRAJECTORY_CAP_CHARS,
        },
        "files": files,
    }
    (args.out_dir / "evidence-index.json").write_text(json.dumps(index, indent=2) + "\n", encoding="utf-8")
    capped_ids = [f["id"] for f in files if f["truncated"]]
    summary = {
        "files": len(files),
        "pass": sum(1 for f in files if f["outcome"] == "PASS"),
        "fail": sum(1 for f in files if f["outcome"] == "FAIL"),
        "trajectories_hitting_cap": len(capped_ids),
        "trajectories_hitting_cap_ids": capped_ids,
        "steps_omitted_by_cap": sum(len(f["omitted_steps"]) for f in files),
        "observations_capped": sum(f["observations_capped"] for f in files),
        "reasoning_content_steps_dropped": sum(f["reasoning_content_steps_dropped"] for f in files),
        "max_evidence_chars": max(f["evidence_chars"] for f in files),
        "total_evidence_chars": sum(f["evidence_chars"] for f in files),
        "total_uncapped_chars": sum(f["uncapped_chars"] for f in files),
    }
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
