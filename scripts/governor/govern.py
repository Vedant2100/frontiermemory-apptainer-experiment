"""Governor pipeline (preregistration v1, section 2): M3 -> arm G, plus size-matched control arm GR.

Steps: segment every M3 topic file; R-artifact flag; judge the other units; admission
(primary: drop contradicted and R-artifact; separation: if the primary rule removes fewer than
5% of non-heading units, also drop insufficient units with a concrete technical assertion);
reassembly; drop files left with headings only; regenerate the index; official check_memory.
GR removes the same number of non-heading units, drawn uniformly with seed 2027, then the same
reassembly and index code.

Refuses to run unless the validation report passes for this model and this judge prompt, and
M3's digest matches the pinned value. Writes only under --out-dir (results/governor-run-<jobid>/).
Logs contain ids, verdicts, and hashes. They never contain unit text, evidence, or reasons.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from random import Random

from common import (CHECKER_SRC, DEFAULT_SEED, EVIDENCE_DIR, EVIDENCE_INDEX, EXPECTED_M3_DIGEST,
                    GROUPS, M3_DIR, M3_INDEX, M3_TOPICS, REPO, UnitKey, append_jsonl, dump_json,
                    read_topic, sha256_file, sha256_text, topic_files)
from evidence import CorpusEvidence
from index_logic import filter_body, regenerate, split_index
from judge import OllamaJudge, prompt_template
from rules import concrete_technical_assertion, r_artifact
from segment import Document, reassemble, parse
from validate import model_digest

SEPARATION_THRESHOLD = 0.05
WORKERS_DEFAULT = 1


def check_memory_folder(folder: Path) -> dict:
    sys.path.insert(0, str(CHECKER_SRC))
    from frontier_memory.memory import check_memory  # official checker, stdlib only

    return check_memory(folder)


def verify_inputs(validation_path: Path, model: str, prompt_sha: str) -> dict:
    report = json.loads(validation_path.read_text(encoding="utf-8"))
    problems = []
    if report.get("gate") != "pass":
        problems.append("validation gate did not pass")
    if report.get("model") != model:
        problems.append(f"validation model {report.get('model')} != {model}")
    if report.get("judge_prompt_sha256") != prompt_sha:
        problems.append("validation was run with a different judge prompt")
    if problems:
        raise SystemExit("refusing to govern: " + "; ".join(problems))
    return report


def verify_m3() -> str:
    report = check_memory_folder(M3_DIR)
    if not report.get("ok"):
        raise SystemExit(f"M3 fails check_memory: {report.get('errors')}")
    if report.get("memory_sha256") != EXPECTED_M3_DIGEST:
        raise SystemExit(f"M3 digest {report.get('memory_sha256')} != pinned {EXPECTED_M3_DIGEST}")
    return report["memory_sha256"]


def load_cache(paths: list[Path], model: str, prompt_sha: str) -> dict[str, dict]:
    cache: dict[str, dict] = {}
    for path in paths:
        if not path.exists():
            continue
        for line in path.read_text(encoding="utf-8").splitlines():
            row = json.loads(line)
            if row["model"] == model and row["prompt_sha256"] == prompt_sha:
                cache[row["key"]] = row
    return cache


def parse_shard(text: str) -> tuple[int, int]:
    index, count = (int(x) for x in text.split("/"))
    if not (0 <= index < count):
        raise SystemExit(f"bad --shard {text}")
    return index, count


def complete_index_for(folder: Path, topics_out: Path, written: list[str], source_index: Path) -> str:
    """Use scripts/complete_memory_index.py when present (it rebuilt M3's index byte-for-byte).

    MEMORY.md in `folder` must already hold the filtered body. Without the script, the
    equivalent logic in index_logic is used. The test suite checks that both agree on M3.
    """
    scripts = REPO / "scripts"
    if str(scripts) not in sys.path:
        sys.path.insert(0, str(scripts))
    try:
        from complete_memory_index import completed_index
    except ImportError:
        return regenerate(source_index, topics_out, written)
    return completed_index(folder)


def write_arm(out_dir: Path, arm: str, docs: dict[str, Document], kept: dict[str, set[int]],
              source_index: Path) -> dict:
    folder = out_dir / f"memory-{arm}"
    topics_out = folder / "topics"
    topics_out.mkdir(parents=True, exist_ok=True)
    for stale in topics_out.glob("*.md"):
        stale.unlink()
    written: list[str] = []
    dropped: list[str] = []
    for name in sorted(docs):
        doc = docs[name]
        keep = kept[name]
        if not any(u.governable and u.uid in keep for u in doc.units()):
            dropped.append(name)
            continue
        (topics_out / name).write_bytes(reassemble(doc, keep).encode("utf-8"))
        written.append(name)
    body, _ = split_index(source_index.read_text(encoding="utf-8"))
    body_text = "\n".join(filter_body(body, set(written))).rstrip("\n") + "\n"
    (folder / "MEMORY.md").write_text(body_text, encoding="utf-8")
    index_text = complete_index_for(folder, topics_out, written, source_index)
    (folder / "MEMORY.md").write_bytes(index_text.encode("utf-8"))
    report = check_memory_folder(folder)
    return {
        "topic_files": len(written),
        "files_dropped_headings_only": len(dropped),
        "governable_units_kept": sum(1 for name in written for u in docs[name].units()
                                     if u.governable and u.uid in kept[name]),
        "check_memory_ok": bool(report.get("ok")),
        "check_memory_errors": report.get("errors", []),
        "memory_sha256": report.get("memory_sha256"),
        "total_bytes": report.get("total_bytes"),
        "file_count": report.get("file_count"),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--out-dir", type=Path, required=True)
    parser.add_argument("--validation-report", type=Path, required=True)
    parser.add_argument("--ollama-url", default="http://127.0.0.1:11434/api/chat")
    parser.add_argument("--model", required=True)
    parser.add_argument("--model-manifest", type=Path, required=True)
    parser.add_argument("--seed", type=int, default=DEFAULT_SEED)
    parser.add_argument("--workers", type=int, default=WORKERS_DEFAULT)
    parser.add_argument("--shard", default="0/1", help="i/n: judge only technical units with index %% n == i")
    parser.add_argument("--judge-only", action="store_true", help="stop after writing judge-cache.jsonl")
    parser.add_argument("--cache-files", default="", help="comma-separated judge caches from other jobs to reuse")
    args = parser.parse_args()

    started = time.time()
    out = args.out_dir
    out.mkdir(parents=True, exist_ok=True)
    timings: dict[str, float] = {}
    shard_index, shard_count = parse_shard(args.shard)

    m3_digest = verify_m3()
    template, prompt_sha = prompt_template()
    validation = verify_inputs(args.validation_report, args.model, prompt_sha)
    if model_digest(args.model_manifest) != validation["model_digest"]:
        raise SystemExit("model manifest digest differs from the validated model")

    # 1. Segment every M3 topic file.
    t0 = time.time()
    docs: dict[str, Document] = {}
    texts: dict[str, str] = {}
    for path in topic_files(M3_TOPICS):
        texts[path.name] = read_topic(path)
        docs[path.name] = parse(texts[path.name])
    units: list[tuple[UnitKey, object]] = []
    for name, doc in docs.items():
        for unit in doc.units():
            if unit.governable:
                units.append((UnitKey(Path(name).stem, unit.uid), unit))
    timings["segment_seconds"] = round(time.time() - t0, 1)

    # 2. Judge technical, non-R-artifact units only (A1). Resumable through judge-cache.jsonl.
    t0 = time.time()
    evidence = CorpusEvidence(EVIDENCE_DIR, EVIDENCE_INDEX, GROUPS)
    cache_path = out / "judge-cache.jsonl"
    cache_paths = [cache_path] + [Path(x) for x in args.cache_files.split(",") if x]
    cache = load_cache(cache_paths, args.model, prompt_sha)
    technical_units = [(k, u) for k, u in units if not r_artifact(u) and concrete_technical_assertion(u)]
    judged: dict[str, dict] = {}
    pending = []
    retrieval: dict[str, tuple[str, list]] = {}
    for position, (key, unit) in enumerate(technical_units):
        if position % shard_count != shard_index:
            continue
        unit_hash = sha256_text(unit.text)
        method, excerpts = evidence.evidence_for(unit.citations, unit.text, key.topic)
        retrieval[key.label()] = (method, excerpts)
        if key.label() in cache and cache[key.label()]["unit_sha256"] == unit_hash:
            judged[key.label()] = cache[key.label()]
        else:
            pending.append((key, unit, unit_hash, method, excerpts))
    judge = OllamaJudge(args.ollama_url, args.model, seed=args.seed)
    with ThreadPoolExecutor(max_workers=max(1, args.workers)) as pool:
        futures = {
            pool.submit(judge.judge, template, unit.text, excerpts): (key, unit_hash, method, excerpts)
            for key, unit, unit_hash, method, excerpts in pending
        }
        for future in as_completed(futures):
            key, unit_hash, method, excerpts = futures[future]
            result = future.result()
            row = {
                "key": key.label(),
                "model": args.model,
                "prompt_sha256": prompt_sha,
                "unit_sha256": unit_hash,
                "verdict": result.verdict,
                "attempts": result.attempts,
                "bad_json": result.bad_json,
            }
            judged[key.label()] = row
            append_jsonl(cache_path, row)
    timings["judge_seconds"] = round(time.time() - t0, 1)
    timings["judge_calls_made"] = len(pending)
    if args.judge_only:
        dump_json(out / "judge-shard-summary.json", {
            "shard": args.shard, "technical_units_total": len(technical_units),
            "units_in_shard": len(retrieval), "calls_made": len(pending),
            "wall_seconds": timings["judge_seconds"]})
        return 0
    missing = [(k, u) for k, u in technical_units if k.label() not in judged]
    if missing:
        raise SystemExit(f"{len(missing)} technical units lack a verdict; run the remaining shards first")

    # 3. Admission (A1). Primary: drop technical units judged contradicted, plus R-artifact.
    #    Non-technical units are always kept. Separation rule: strict when primary < 5%.
    rows = []
    primary_removed: set[str] = set()
    for key, unit in units:
        label = key.label()
        is_r = r_artifact(unit)
        technical = concrete_technical_assertion(unit)
        if is_r:
            verdict = "not_judged_r_artifact"
        elif not technical:
            verdict = "not_judged_nontechnical"
        else:
            verdict = judged[label]["verdict"]
        method = retrieval[label][0] if label in retrieval else "not_retrieved"
        rows.append({"key": key, "unit": unit, "label": label, "r_artifact": is_r,
                     "technical": technical, "verdict": verdict, "method": method,
                     "bad_json": judged.get(label, {}).get("bad_json", False),
                     "attempts": judged.get(label, {}).get("attempts", 0),
                     "unit_sha256": sha256_text(unit.text)})
        if is_r or verdict == "contradicted":
            primary_removed.add(label)
    total = len(units)
    primary_fraction = len(primary_removed) / total
    strict = primary_fraction < SEPARATION_THRESHOLD
    removed = set(primary_removed)
    strict_removed: set[str] = set()
    if strict:
        for row in rows:
            if row["technical"] and row["verdict"] == "insufficient":
                strict_removed.add(row["label"])
        removed |= strict_removed

    # 4. Arm G.
    kept_g = {name: set() for name in docs}
    for key, unit in units:
        if key.label() not in removed:
            kept_g[key.topic + ".md"].add(unit.uid)
    g_stats = write_arm(out, "G", docs, kept_g, M3_INDEX)

    # 5. Arm GR: same number of removed units, uniform at random over all non-heading units.
    population = [key for key, _ in units]
    rng = Random(args.seed)
    chosen = set(rng.sample(population, len(removed)))
    kept_gr = {name: set() for name in docs}
    for key, unit in units:
        if key not in chosen:
            kept_gr[key.topic + ".md"].add(unit.uid)
    gr_stats = write_arm(out, "GR", docs, kept_gr, M3_INDEX)

    # 6. Per-unit decision log (ids, verdicts, hashes only).
    log_path = out / "unit-decisions.jsonl"
    if log_path.exists():
        log_path.unlink()
    for row in rows:
        key = row["key"]
        append_jsonl(log_path, {
            "unit": row["label"],
            "kind": row["unit"].kind,
            "unit_sha256": row["unit_sha256"],
            "r_artifact": row["r_artifact"],
            "technical": row["technical"],
            "citations": len(row["unit"].citations),
            "evidence_method": row["method"],
            "evidence_ids": [f"{e.trajectory}#{e.step}" for e in retrieval.get(row["label"], ("", []))[1]],
            "verdict": row["verdict"],
            "bad_json": row["bad_json"],
            "attempts": row["attempts"],
            "removed_primary": row["label"] in primary_removed,
            "removed_strict": row["label"] in strict_removed,
            "removed_G": row["label"] in removed,
            "removed_GR": key in chosen,
        })

    verdicts = Counter(row["verdict"] for row in rows)
    summary = {
        "model": args.model,
        "model_digest": validation["model_digest"],
        "judge_prompt_sha256": prompt_sha,
        "validation_report": str(args.validation_report),
        "validation_gate": validation["gate"],
        "validation_sensitivity": validation["sensitivity"],
        "validation_specificity": validation["specificity"],
        "m3_memory_sha256": m3_digest,
        "governable_units": total,
        "r_artifact_units": sum(1 for r in rows if r["r_artifact"]),
        "technical_units": sum(1 for r in rows if r["technical"] and not r["r_artifact"]),
        "nontechnical_units_kept": sum(1 for r in rows if not r["technical"] and not r["r_artifact"]),
        "verdicts": dict(sorted(verdicts.items())),
        "evidence_methods": dict(sorted(Counter(r["method"] for r in rows).items())),
        "bad_json_flags": sum(1 for r in rows if r["bad_json"]),
        "primary_removed": len(primary_removed),
        "primary_removed_fraction": primary_fraction,
        "separation_rule_applied": "strict" if strict else "primary",
        "strict_removed_insufficient_technical": len(strict_removed),
        "total_removed_G": len(removed),
        "arm_G": g_stats,
        "arm_GR": gr_stats,
        "wall_seconds": round(time.time() - started, 1),
        "timings": timings,
    }
    dump_json(out / "summary.json", summary)
    print(json.dumps({k: summary[k] for k in ("governable_units", "r_artifact_units", "technical_units",
                                               "verdicts", "primary_removed", "primary_removed_fraction",
                                               "separation_rule_applied", "total_removed_G")}, indent=2))
    print(json.dumps({"G": {k: g_stats[k] for k in ("topic_files", "check_memory_ok", "memory_sha256")},
                      "GR": {k: gr_stats[k] for k in ("topic_files", "check_memory_ok", "memory_sha256")}}, indent=2))
    return 0 if g_stats["check_memory_ok"] and gr_stats["check_memory_ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
