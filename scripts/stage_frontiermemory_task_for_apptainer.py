#!/usr/bin/env python3
"""Create a local Harbor task view for an official task and local Apptainer SIF.

The downloaded source task is left untouched. The copy points Harbor at local
SIFs, adjusts its network policy, and uses a local patch collector that captures
committed, uncommitted, and untracked agent edits. Task instructions, tests,
verifier code, and solution files are copied verbatim.
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import tomllib
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
    destination_resolved = destination.resolve()
    for payload in (args.opencode_runtime.resolve(), args.opencode_shims.resolve()):
        try:
            payload.relative_to(destination_resolved)
        except ValueError:
            continue
        raise ValueError(
            f"OpenCode payload {payload} is inside the output task that will be replaced; "
            "use the shared payload outside --output-root"
        )
    if destination.exists():
        shutil.rmtree(destination)
    shutil.copytree(source, destination, symlinks=True)

    copied_toml = destination / "task.toml"
    content = copied_toml.read_text(encoding="utf-8")
    with task_toml.open("rb") as stream:
        official_config = tomllib.load(stream)
    base_commit = official_config.get("metadata", {}).get("base_commit_hash")
    if not base_commit:
        raise ValueError("Official task metadata has no base_commit_hash")

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

    # Harbor's standard git-diff collector misses uncommitted/untracked source
    # edits in this Apptainer handoff. Override only the staged task copy's
    # collector; the original verifier and official task remain untouched.
    collector_command = (
        "cd /app && mkdir -p /logs/artifacts && "
        "git config --global --add safe.directory /app && git add -A && "
        f"git diff --binary {base_commit} -- > /logs/artifacts/model.patch"
    )
    collector_pattern = re.compile(
        r'(?ms)(\[\[verifier\.collect\]\]\s*\ncommand\s*=\s*)"[^"\n]*"'
    )
    content, collector_count = collector_pattern.subn(
        lambda match: match.group(1) + json.dumps(collector_command), content
    )
    if collector_count != 1:
        raise ValueError(f"Expected one verifier collector command; found {collector_count}")
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
            "verifier.collect": "local staged-task adapter runs git add -A then diffs against the official base commit so uncommitted and untracked agent edits are captured; original verifier scripts are unchanged",
        },
        "network_mode_fields_changed": network_count,
        "collector_base_commit": base_commit,
        "official_task_source_unchanged": True,
    }
    (destination / "apptainer-adaptation.json").write_text(
        json.dumps(record, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(record, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
