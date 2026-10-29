#!/usr/bin/env python3
"""Stage an untouched Word2Vec task copy with local Apptainer images."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import tomllib
from pathlib import Path


def set_section_key(text: str, section_name: str, key: str, value: str) -> str:
    header = f"[{section_name}]"
    match = re.search(rf"(?m)^{re.escape(header)}\s*$", text)
    if match is None:
        raise ValueError(f"Missing TOML section {header}")
    body_start = match.end()
    # Array-of-tables headers such as [[verifier.collect]] also end a section (otherwise keys are appended to them).
    next_section = re.search(r"(?m)^\[\[?[^\]]+\]\]?\s*$", text[body_start:])
    body_end = body_start + next_section.start() if next_section else len(text)
    body = text[body_start:body_end]
    replacement = f"{key} = {json.dumps(value)}"
    key_pattern = re.compile(rf"(?m)^[ \t]*{re.escape(key)}\s*=.*$")
    if key_pattern.search(body):
        body = key_pattern.sub(replacement, body, count=1)
    else:
        body = body.rstrip() + "\n" + replacement + "\n"
    return text[:body_start] + body + text[body_end:]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--agent-image", type=Path, required=True)
    parser.add_argument("--verifier-image", type=Path, required=True)
    args = parser.parse_args()

    source = args.source.resolve()
    destination = args.output.resolve()
    task_file = source / "task.toml"
    if not task_file.is_file():
        raise FileNotFoundError(task_file)
    if not args.agent_image.is_file() or not args.verifier_image.is_file():
        raise FileNotFoundError("Both local Apptainer images must exist before staging")
    if destination.exists():
        shutil.rmtree(destination)
    shutil.copytree(source, destination, symlinks=True)

    text = (destination / "task.toml").read_text(encoding="utf-8")
    text = set_section_key(
        text,
        "environment",
        "docker_image",
        str(args.agent_image.resolve()),
    )
    text = set_section_key(
        text,
        "verifier.environment",
        "docker_image",
        str(args.verifier_image.resolve()),
    )
    source_config = tomllib.loads(text)
    original_verifier_network_mode = source_config["verifier"]["environment"].get(
        "network_mode", "public"
    )
    # Harbor's Singularity backend rejects no-network even when the verifier
    # itself needs no external services. Adapt only the disposable local task
    # copy; this cannot enforce egress isolation and must be reported as a
    # nonstandard Apptainer evaluation.
    text = set_section_key(
        text,
        "verifier.environment",
        "network_mode",
        "public",
    )
    # Harbor's Singularity backend also rejects no-network for the agent. Only a declared [agent] network_mode is
    # changed (the word2vec and DAPT tasks declare none, so their staged copies are unchanged).
    # The same applies to a top-level [verifier] network_mode (declared by the patch tasks, not by word2vec or DAPT).
    for section_name in ("agent", "verifier"):
        section = re.search(rf"(?ms)^\[{section_name}\]\s*$(.*?)(?=^\[|\Z)", text)
        if section and re.search(r"(?m)^[ \t]*network_mode\s*=", section.group(1)):
            text = set_section_key(text, section_name, "network_mode", "public")
    (destination / "task.toml").write_text(text, encoding="utf-8")

    config = tomllib.loads(text)
    assert config["environment"]["docker_image"] == str(args.agent_image.resolve())
    assert (
        config["verifier"]["environment"]["docker_image"]
        == str(args.verifier_image.resolve())
    )
    assert config["verifier"]["environment"]["network_mode"] == "public"
    print(
        json.dumps(
            {
                "source_task": str(source),
                "staged_task": str(destination),
                "task_name": config["task"]["name"],
                "agent_image": config["environment"]["docker_image"],
                "verifier_image": config["verifier"]["environment"]["docker_image"],
                "official_task_payload_files_copied_verbatim": True,
                "task_toml_runtime_adaptations": {
                    "local_agent_and_verifier_image_paths": True,
                    "verifier_network_mode": {
                        "official": original_verifier_network_mode,
                        "staged": "public",
                        "reason": "Harbor Singularity rejects no-network",
                    },
                },
                "network_egress_isolation_enforced": False,
                "source_task_toml_sha256": hashlib.sha256(task_file.read_bytes()).hexdigest(),
                "staged_task_toml_sha256": hashlib.sha256(
                    (destination / "task.toml").read_bytes()
                ).hexdigest(),
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
