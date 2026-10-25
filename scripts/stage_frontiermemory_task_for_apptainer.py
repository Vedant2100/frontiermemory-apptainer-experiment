#!/usr/bin/env python3
"""Create a local Harbor task view for an official task and local Apptainer SIF.

The downloaded source task is left untouched. The copy changes only the image
reference and network policy required by Harbor's Singularity backend; task
instructions, tests, verifier code, and solution files are copied verbatim.
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-root", type=Path, required=True)
    parser.add_argument("--task-id", required=True)
    parser.add_argument("--image", type=Path, required=True)
    parser.add_argument("--verifier-image", type=Path, required=True)
    parser.add_argument("--opencode-runtime", type=Path, required=True)
    parser.add_argument("--opencode-shims", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    args = parser.parse_args()

    source = args.source_root / args.task_id
    destination = args.output_root / args.task_id
    task_toml = source / "task.toml"
    if not task_toml.is_file():
        raise FileNotFoundError(task_toml)
    if not args.image.is_file():
        raise FileNotFoundError(args.image)
    if not args.verifier_image.is_file():
        raise FileNotFoundError(args.verifier_image)
    if not args.opencode_runtime.is_dir():
        raise FileNotFoundError(args.opencode_runtime)
    if not args.opencode_shims.is_dir():
        raise FileNotFoundError(args.opencode_shims)
    if destination.exists():
        shutil.rmtree(destination)
    shutil.copytree(source, destination, symlinks=True)

    copied_toml = destination / "task.toml"
    content = copied_toml.read_text(encoding="utf-8")
    image_pattern = re.compile(r'(?m)^(docker_image\s*=\s*)"[^"]+"$')
    content, image_count = image_pattern.subn(
        lambda match: f'{match.group(1)}"{args.image.resolve()}"', content
    )
    if image_count != 1:
        raise ValueError(f"Expected exactly one environment image setting; found {image_count}")

    verifier_environment = "[verifier.environment]"
    verifier_image = f'docker_image = "{args.verifier_image.resolve()}"\n'
    if verifier_environment not in content:
        raise ValueError("Expected a separate [verifier.environment] section")
    section_start = content.index(verifier_environment) + len(verifier_environment)
    next_section = re.search(r"(?m)^\[[^\]]+\]", content[section_start:])
    section_end = section_start + next_section.start() if next_section else len(content)
    section = content[section_start:section_end]
    if re.search(r"(?m)^\s*docker_image\s*=", section):
        section = re.sub(
            r'(?m)^(\s*docker_image\s*=\s*)"[^"]+"\s*$',
            lambda match: f'{match.group(1)}"{args.verifier_image.resolve()}"',
            section,
            count=1,
        )
    else:
        section = "\n" + verifier_image + section.lstrip("\n")
    content = content[:section_start] + section + content[section_end:]

    content, network_count = re.subn(
        r'(?m)^(\s*network_mode\s*=\s*)"no-network"\s*$',
        r'\1"public"',
        content,
    )
    if network_count < 2:
        raise ValueError(f"Expected agent and verifier network settings; found {network_count}")
    copied_toml.write_text(content, encoding="utf-8")

    environment_files = destination / "environment" / "files"
    environment_files.mkdir(parents=True, exist_ok=True)
    shutil.copytree(
        args.opencode_runtime,
        environment_files / "opencode-runtime",
        symlinks=True,
        dirs_exist_ok=True,
    )
    shutil.copytree(
        args.opencode_shims,
        environment_files / "shims",
        symlinks=True,
        dirs_exist_ok=True,
    )

    record = {
        "task_id": args.task_id,
        "official_source": str(source.resolve()),
        "run_copy": str(destination.resolve()),
        "apptainer_image": str(args.image.resolve()),
        "verifier_apptainer_image": str(args.verifier_image.resolve()),
        "changes": {
            "environment.docker_image": "local official-task image converted to SIF",
            "verifier.environment.docker_image": "local image based on the official task SIF with verifier files copied unchanged to /tests and any missing upstream source tree plus Git metadata restored at the exact task base commit",
            "network_mode": "public (Harbor Singularity backend does not enforce no-network)",
            "environment.files": "reused preinstalled OpenCode 1.19.4 and offline npm shims",
        },
        "network_mode_fields_changed": network_count,
    }
    (destination / "apptainer-adaptation.json").write_text(
        json.dumps(record, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(record, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
