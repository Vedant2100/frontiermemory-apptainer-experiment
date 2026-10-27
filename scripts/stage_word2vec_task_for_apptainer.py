#!/usr/bin/env python3
"""Stage an untouched Word2Vec task copy with local Apptainer images."""

from __future__ import annotations

import argparse
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
    next_section = re.search(r"(?m)^\[[^\]]+\]\s*$", text[body_start:])
    body_end = body_start + next_section.start() if next_section else len(text)
    body = text[body_start:body_end]
    replacement = f"{key} = {json.dumps(value)}"
    key_pattern = re.compile(rf"(?m)^\s*{re.escape(key)}\s*=.*$")
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
    (destination / "task.toml").write_text(text, encoding="utf-8")

    config = tomllib.loads(text)
    assert config["environment"]["docker_image"] == str(args.agent_image.resolve())
    assert (
        config["verifier"]["environment"]["docker_image"]
        == str(args.verifier_image.resolve())
    )
    print(
        json.dumps(
            {
                "source_task": str(source),
                "staged_task": str(destination),
                "task_name": config["task"]["name"],
                "agent_image": config["environment"]["docker_image"],
                "verifier_image": config["verifier"]["environment"]["docker_image"],
                "official_task_files_copied_verbatim": True,
                "only_task_toml_image_paths_adapted": True,
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
