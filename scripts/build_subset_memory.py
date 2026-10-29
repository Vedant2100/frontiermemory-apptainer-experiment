#!/usr/bin/env python3
"""Build the R25 arm: memory from a stratified random 25% subset of the corpus.

Selection (deterministic; depends only on trajectory ids and the PASS/FAIL labels recorded in
evidence-index.json): per outcome stratum, ids are sorted and drawn with random.Random(SEED).sample.
Stratum sizes are allocated proportionally with largest-remainder rounding so the subset totals
25% of the corpus (674 -> 168). Map notes are reused from the v5 run (map is per trajectory); the
selected note files are copied, not linked, into the R25 run dir.

Stages (all reuse scripts/generate_corpus_memory_v5.py unchanged: same prompts and settings):
  select   write selection.json, selected-ids.txt, copy evidence index and selected notes (CPU only)
  run      select (verify-or-create), then group -> reduce -> finalize -> complete index (needs Ollama)

The final folder is <run-dir>/memory-final: the finalize output with MEMORY.md replaced by the
complete_memory_index.py result.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import random
import shutil
import sys
import time
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPTS))  # python -I drops the script directory from sys.path
import complete_memory_index as completer  # noqa: E402
import generate_corpus_memory_v5 as v5  # noqa: E402

REPO = SCRIPTS.parent
V5_RUN = REPO / "results" / "memory-generation-v5"
RUN_DIR = REPO / "results" / "memory-generation-r25"
SEED = 2027
SUBSET_FRACTION = 0.25


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def select_ids() -> dict:
    index = json.loads((V5_RUN / "evidence-index.json").read_text(encoding="utf-8"))
    strata: dict[str, list[str]] = {}
    for entry in index["files"]:
        strata.setdefault(entry["outcome"], []).append(entry["id"])
    total = sum(len(ids) for ids in strata.values())
    target = int(total * SUBSET_FRACTION)  # 674 * 0.25 = 168.5 -> 168
    exact = {k: target * len(v) / total for k, v in strata.items()}
    alloc = {k: int(x) for k, x in exact.items()}
    shortfall = target - sum(alloc.values())
    for k in sorted(strata, key=lambda k: (-(exact[k] - alloc[k]), k))[:shortfall]:
        alloc[k] += 1
    rng = random.Random(SEED)
    selected: list[str] = []
    for outcome in sorted(strata):
        selected += rng.sample(sorted(strata[outcome]), alloc[outcome])
    selected.sort()
    assert len(selected) == len(set(selected)) == target
    return {
        "seed": SEED,
        "fraction": SUBSET_FRACTION,
        "corpus_size": total,
        "corpus_outcome_counts": {k: len(v) for k, v in sorted(strata.items())},
        "selected_outcome_counts": {k: alloc[k] for k in sorted(alloc)},
        "selected_count": len(selected),
        "selected_ids_sha256": sha256_text("\n".join(selected) + "\n"),
        "selected_ids": selected,
        "method": "per-outcome random.Random(seed).sample over sorted ids; largest-remainder allocation",
        "corpus_manifest_sha256": index["corpus_manifest_sha256"],
    }


def cmd_select() -> dict:
    RUN_DIR.mkdir(parents=True, exist_ok=True)
    (RUN_DIR / "logs").mkdir(exist_ok=True)
    selection = select_ids()
    selection_path = RUN_DIR / "selection.json"
    if selection_path.exists():
        previous = json.loads(selection_path.read_text(encoding="utf-8"))
        if previous["selected_ids_sha256"] != selection["selected_ids_sha256"]:
            raise SystemExit("existing selection.json does not match the seeded selection")
    else:
        selection_path.write_text(json.dumps(selection, indent=2) + "\n", encoding="utf-8")
    (RUN_DIR / "selected-ids.txt").write_text("\n".join(selection["selected_ids"]) + "\n", encoding="utf-8")
    shutil.copy2(V5_RUN / "evidence-index.json", RUN_DIR / "evidence-index.json")
    notes_dst = RUN_DIR / "notes"
    notes_dst.mkdir(exist_ok=True)
    copied = 0
    chosen = set(selection["selected_ids"])
    for note_id in selection["selected_ids"]:
        src = V5_RUN / "notes" / f"{note_id}.json"
        dst = notes_dst / f"{note_id}.json"
        if not dst.exists() or dst.read_bytes() != src.read_bytes():
            shutil.copy2(src, dst)
            copied += 1
    extra = [p.name for p in notes_dst.glob("*.json") if p.stem not in chosen]
    if extra:
        raise SystemExit(f"unexpected notes in R25 run dir: {len(extra)}")
    print(json.dumps({k: v for k, v in selection.items() if k != "selected_ids"}, indent=2))
    print(f"notes present: {len(list(notes_dst.glob('*.json')))}, copied this call: {copied}")
    return selection


def cmd_run(api: str) -> int:
    selection = cmd_select()
    timings: dict[str, float] = {}
    started = time.monotonic()
    ns = argparse.Namespace(run_dir=RUN_DIR, api=api)

    t = time.monotonic()
    groups_summary = v5.cmd_group(ns)
    timings["group_seconds"] = round(time.monotonic() - t, 1)

    t = time.monotonic()
    rc = v5.cmd_reduce(ns)
    timings["reduce_seconds"] = round(time.monotonic() - t, 1)
    if rc != 0:
        print("reduce reported failures; rerun resumes from completed groups", flush=True)
        return rc

    t = time.monotonic()
    rc = v5.cmd_finalize(ns)  # writes memory/MEMORY.md (LLM index) and the checker report
    timings["finalize_seconds"] = round(time.monotonic() - t, 1)
    if rc != 0:
        print("finalize checker failed on the LLM index", flush=True)
        return rc

    src = RUN_DIR / "memory"
    final = RUN_DIR / "memory-final"
    if final.exists():
        shutil.rmtree(final)
    shutil.copytree(src, final, ignore=shutil.ignore_patterns("MEMORY.md"))
    completed = completer.completed_index(src)
    (final / "MEMORY.md").write_text(completed, encoding="utf-8")
    timings["total_seconds"] = round(time.monotonic() - started, 1)

    summary = {
        "selection": {k: v for k, v in selection.items() if k != "selected_ids"},
        "groups": groups_summary,
        "timings": timings,
        "model": v5.MODEL,
        "context": v5.CONTEXT,
        "temperature": v5.TEMPERATURE,
        "reduce_num_predict": v5.REDUCE_NUM_PREDICT,
        "index_num_predict": v5.INDEX_NUM_PREDICT,
        "topic_files": len(list((final / "topics").glob("*.md"))),
        "completed_index_sha256": sha256_text(completed),
    }
    (RUN_DIR / "logs" / "subset-run-summary.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    print(f"complete index written to {final / 'MEMORY.md'}", flush=True)
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("select")
    run = sub.add_parser("run")
    run.add_argument("--api", default="http://127.0.0.1:11434/api/chat")
    args = parser.parse_args()
    if args.command == "select":
        cmd_select()
        return 0
    return cmd_run(args.api)


if __name__ == "__main__":
    sys.exit(main())
