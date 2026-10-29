"""Shared paths, loaders, and hashing for the governor (preregistration v1, section 2)."""

from __future__ import annotations

import hashlib
import json
import sys
from dataclasses import dataclass
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
sys.path.insert(0, str(HERE))

M3_DIR = REPO / "memory" / "frozen-v5-fullindex"
M3_TOPICS = M3_DIR / "topics"
M3_INDEX = M3_DIR / "MEMORY.md"
V5_RUN = REPO / "results" / "memory-generation-v5"
EVIDENCE_DIR = V5_RUN / "evidence"
EVIDENCE_INDEX = V5_RUN / "evidence-index.json"
GROUPS = V5_RUN / "groups.json"
PROMPT = HERE / "judge_prompt.md"
CHECKER_SRC = REPO / "frontiermemory" / "src"

# Pinned in the memory generator. The governor refuses to run if the pinned values differ.
EXPECTED_M3_DIGEST = "4a2eb5286366d650260af0b873a91be9f99b2891a327f0ae73ba8c2e8ef0517a"
DEFAULT_SEED = 2027


@dataclass(frozen=True)
class UnitKey:
    topic: str
    uid: int

    def label(self) -> str:
        return f"{self.topic}#u{self.uid:04d}"


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read_topic(path: Path) -> str:
    # newline="" keeps the file's bytes exact, so reassembly can be compared byte-for-byte.
    return path.read_bytes().decode("utf-8")


def topic_files(root: Path = M3_TOPICS) -> list[Path]:
    return sorted(root.glob("*.md"), key=lambda p: p.name)


def dump_json(path: Path, obj) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def append_jsonl(path: Path, obj) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(obj, sort_keys=True) + "\n")
