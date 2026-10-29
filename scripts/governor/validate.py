"""Judge validation before freeze (preregistration v1, section 2.6, as amended by A1).
No human labels, no task data.

Sample (A1): 100 non-heading, non-R-artifact units from M3 with at least one resolvable citation,
drawn with seed 2027 from the sorted list. Each sampled unit gets one perturbation (number, flag,
identifier, or negation) chosen by the seeded RNG from those that are detectable: a changed token
occurs as a whole token in the unit's cited evidence.

Judging: every unit is judged against its own cited evidence (the same excerpts for the original
and the perturbed text).
  sensitivity = share of perturbed units judged `contradicted`
  specificity = share of the unperturbed units judged `supported` or `insufficient`
Gate: sensitivity >= 0.6 and specificity >= 0.8. Exit code 0 means pass, 3 means the gate failed.
The governor refuses to run unless this report says pass for the same model and prompt digest.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from concurrent.futures import ThreadPoolExecutor
import time
from collections import Counter
from pathlib import Path
from random import Random

from common import (DEFAULT_SEED, EVIDENCE_DIR, EVIDENCE_INDEX, GROUPS, M3_TOPICS, PROMPT,
                    REPO, UnitKey, append_jsonl, dump_json, read_topic, sha256_file,
                    sha256_text, topic_files)
from evidence import CorpusEvidence
from judge import OllamaJudge, prompt_template
from perturb import applicable, detectable, file_identifier_pool
from rules import r_artifact
from segment import parse

SAMPLE_SIZE = 100
SENSITIVITY_GATE = 0.6
SPECIFICITY_GATE = 0.8
EXIT_GATE_FAILED = 3


def model_digest(manifest: Path) -> dict:
    data = json.loads(manifest.read_bytes())
    model_layers = [layer["digest"] for layer in data["layers"]
                    if layer["mediaType"].endswith("image.model")]
    return {"manifest_sha256": sha256_file(manifest), "model_layer": model_layers[0] if model_layers else None}


def eligible_units(evidence: CorpusEvidence):
    """Sorted (UnitKey, unit, file_text) for every judged unit with a resolvable citation."""
    out = []
    for path in topic_files(M3_TOPICS):
        text = read_topic(path)
        for unit in parse(text).units():
            if not unit.governable or r_artifact(unit):
                continue
            if not evidence.resolvable(unit.citations):
                continue
            out.append((UnitKey(path.stem, unit.uid), unit, text))
    return out


def draw_sample(units, seed: int, evidence: CorpusEvidence):
    """Seeded draw of SAMPLE_SIZE units with at least one detectable perturbation (A1)."""
    rng = Random(seed)
    order = list(units)
    rng.shuffle(order)
    pools: dict[str, list[str]] = {}
    chosen = []
    for key, unit, text in order:
        if key.topic not in pools:
            pools[key.topic] = file_identifier_pool(text)
        perts = applicable(unit, pools[key.topic], rng)
        _method, excerpts = evidence.evidence_for(unit.citations, unit.text, key.topic)
        evidence_text = "\n".join(e.text for e in excerpts)
        perts = {k: v for k, v in perts.items() if detectable(unit.text, v, evidence_text)}
        if not perts:
            continue
        kind = rng.choice(sorted(perts))
        chosen.append({"key": key, "unit": unit, "perturbed_kind": kind, "perturbed_text": perts[kind]})
        if len(chosen) == SAMPLE_SIZE:
            break
    return chosen


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--out-dir", type=Path, required=True)
    parser.add_argument("--ollama-url", default="http://127.0.0.1:11434/api/chat")
    parser.add_argument("--model", required=True)
    parser.add_argument("--model-manifest", type=Path, required=True)
    parser.add_argument("--seed", type=int, default=DEFAULT_SEED)
    parser.add_argument("--workers", type=int, default=4)
    args = parser.parse_args()
    tag = re.sub(r"[^A-Za-z0-9.]+", "-", args.model).strip("-")

    started = time.time()
    out = args.out_dir
    out.mkdir(parents=True, exist_ok=True)
    template, prompt_sha = prompt_template()
    evidence = CorpusEvidence(EVIDENCE_DIR, EVIDENCE_INDEX, GROUPS)
    judge = OllamaJudge(args.ollama_url, args.model, seed=args.seed)

    units = eligible_units(evidence)
    sample = draw_sample(units, args.seed, evidence)
    if len(sample) < SAMPLE_SIZE:
        raise SystemExit(f"only {len(sample)} perturbable units available")

    log_path = out / f"validation-units-{tag}.jsonl"
    if log_path.exists():
        log_path.unlink()
    tally = Counter()
    per_type = Counter()
    per_type_contra = Counter()

    def run_one(item):
        key, unit = item["key"], item["unit"]
        method, excerpts = evidence.evidence_for(unit.citations, unit.text, key.topic)
        original = judge.judge(template, unit.text, excerpts)
        perturbed = judge.judge(template, item["perturbed_text"], excerpts)
        return item, method, excerpts, original, perturbed

    with ThreadPoolExecutor(max_workers=max(1, args.workers)) as pool:
        results = list(pool.map(run_one, sample))
    for item, method, excerpts, original, perturbed in results:
        key, unit = item["key"], item["unit"]
        tally["original_" + original.verdict] += 1
        tally["perturbed_" + perturbed.verdict] += 1
        tally["bad_json"] += int(original.bad_json) + int(perturbed.bad_json)
        per_type[item["perturbed_kind"]] += 1
        per_type_contra[item["perturbed_kind"]] += int(perturbed.verdict == "contradicted")
        append_jsonl(log_path, {
            "unit": key.label(),
            "kind": unit.kind,
            "unit_sha256": sha256_text(unit.text),
            "perturbation": item["perturbed_kind"],
            "perturbed_sha256": sha256_text(item["perturbed_text"]),
            "evidence_method": method,
            "evidence_ids": [f"{e.trajectory}#{e.step}" for e in excerpts],
            "original_verdict": original.verdict,
            "original_attempts": original.attempts,
            "perturbed_verdict": perturbed.verdict,
            "perturbed_attempts": perturbed.attempts,
        })

    n = len(sample)
    sensitivity = tally["perturbed_contradicted"] / n
    specificity = (tally["original_supported"] + tally["original_insufficient"]) / n
    passed = sensitivity >= SENSITIVITY_GATE and specificity >= SPECIFICITY_GATE
    report = {
        "gate": "pass" if passed else "fail",
        "sensitivity": sensitivity,
        "specificity": specificity,
        "gates": {"sensitivity_min": SENSITIVITY_GATE, "specificity_min": SPECIFICITY_GATE},
        "sample_size": n,
        "eligible_units": len(units),
        "seed": args.seed,
        "validation_set": "a1-detectable",
        "workers": args.workers,
        "model": args.model,
        "model_digest": model_digest(args.model_manifest),
        "judge_prompt_sha256": prompt_sha,
        "judge_prompt_path": str(PROMPT.relative_to(REPO)),
        "original_verdicts": {k: tally["original_" + k] for k in ("supported", "contradicted", "insufficient")},
        "perturbed_verdicts": {k: tally["perturbed_" + k] for k in ("supported", "contradicted", "insufficient")},
        "perturbation_counts": dict(sorted(per_type.items())),
        "sensitivity_by_perturbation": {k: per_type_contra[k] / per_type[k] for k in sorted(per_type)},
        "bad_json_flags": tally["bad_json"],
        "wall_seconds": round(time.time() - started, 1),
    }
    dump_json(out / f"validation-a1-{tag}.json", report)
    print(json.dumps({k: report[k] for k in ("gate", "sensitivity", "specificity", "sample_size",
                                              "original_verdicts", "perturbed_verdicts",
                                              "perturbation_counts", "bad_json_flags")}, indent=2))
    return 0 if passed else EXIT_GATE_FAILED


if __name__ == "__main__":
    sys.exit(main())
