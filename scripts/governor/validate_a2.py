"""Validation of the A2 grounding rule on the same 100-unit A1 set (preregistration v1, amendment A2).

Sensitivity = share of perturbed units dropped by the A2 admission rule (technical and ungrounded).
Specificity = share of the original (unperturbed) units kept.
Gate: sensitivity >= 0.6 and specificity >= 0.8. Exit 0 pass, 3 fail. No revisions are allowed.
Writes validation-a2.json. Uses no model and no GPU.
"""

from __future__ import annotations

import argparse
import sys
from collections import Counter
from pathlib import Path

from common import DEFAULT_SEED, EVIDENCE_DIR, EVIDENCE_INDEX, GROUPS, dump_json
from evidence import CorpusEvidence
from grounding import concrete_tokens, grounding
from rules import concrete_technical_assertion, r_artifact
from segment import parse
from validate import SAMPLE_SIZE, draw_sample, eligible_units

SENSITIVITY_GATE = 0.6
SPECIFICITY_GATE = 0.8


def dropped(unit_text_obj, excerpt_texts: list[str]) -> tuple[bool, bool]:
    """Return (dropped, technical) for a unit's text under the A2 admission rule."""
    unit = parse(unit_text_obj).units()[0]
    if r_artifact(unit):
        return True, False
    if not concrete_technical_assertion(unit):
        return False, False
    grounded, _missing = grounding(unit, excerpt_texts)
    return (not grounded), True


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out-dir", type=Path, required=True)
    parser.add_argument("--seed", type=int, default=DEFAULT_SEED)
    args = parser.parse_args()
    args.out_dir.mkdir(parents=True, exist_ok=True)

    evidence = CorpusEvidence(EVIDENCE_DIR, EVIDENCE_INDEX, GROUPS)
    units = eligible_units(evidence)
    sample = draw_sample(units, args.seed, evidence)
    if len(sample) < SAMPLE_SIZE:
        raise SystemExit(f"only {len(sample)} units in the A1 set")

    per_type = Counter()
    per_type_dropped = Counter()
    originals_kept = 0
    originals_zero_tokens = 0
    perturbed_dropped = 0
    originals_technical = 0
    perturbed_technical = 0
    for item in sample:
        unit = item["unit"]
        _method, excerpts = evidence.evidence_for(unit.citations, unit.text, item["key"].topic)
        texts = [e.text for e in excerpts]
        orig_dropped, orig_tech = dropped(unit.text, texts)
        pert_dropped, pert_tech = dropped(item["perturbed_text"], texts)
        originals_kept += int(not orig_dropped)
        originals_technical += int(orig_tech)
        originals_zero_tokens += int(concrete_tokens(unit.text).count == 0)
        kind = item["perturbed_kind"]
        per_type[kind] += 1
        perturbed_dropped += int(pert_dropped)
        per_type_dropped[kind] += int(pert_dropped)
        perturbed_technical += int(pert_tech)

    n = len(sample)
    sensitivity = perturbed_dropped / n
    specificity = originals_kept / n
    passed = sensitivity >= SENSITIVITY_GATE and specificity >= SPECIFICITY_GATE
    report = {
        "rule": "A2 deterministic grounding",
        "gate": "pass" if passed else "fail",
        "sensitivity": sensitivity,
        "specificity": specificity,
        "gates": {"sensitivity_min": SENSITIVITY_GATE, "specificity_min": SPECIFICITY_GATE},
        "sample_size": n,
        "validation_set": "a1-detectable (same units and perturbations as A1)",
        "seed": args.seed,
        "perturbation_counts": dict(sorted(per_type.items())),
        "sensitivity_by_perturbation": {k: per_type_dropped[k] / per_type[k] for k in sorted(per_type)},
        "originals_technical": originals_technical,
        "perturbed_technical": perturbed_technical,
        "originals_with_zero_concrete_tokens": originals_zero_tokens,
        "originals_kept": originals_kept,
        "perturbed_dropped": perturbed_dropped,
    }
    dump_json(args.out_dir / "validation-a2.json", report)
    print({k: report[k] for k in ("gate", "sensitivity", "specificity", "perturbed_dropped", "originals_kept",
                                  "sensitivity_by_perturbation", "originals_with_zero_concrete_tokens",
                                  "originals_technical", "perturbed_technical")})
    return 0 if passed else 3


if __name__ == "__main__":
    sys.exit(main())
