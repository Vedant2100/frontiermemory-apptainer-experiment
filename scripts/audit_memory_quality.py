"""Memory-quality audit (preregistration v1, section 5 and amendment A3). Measurement only.

For each memory arm (M2, M3, R25) it reports counts and rates over the topic files:
unit counts, code-block units longer than 12 lines, R-artifacts, the share of units with
resolvable citations, and the A2 grounding rate over all technical units (split by cited vs BM25
evidence), plus vacuous technical units.

Wiring is the same as validate_a2.py and govern.py: segment.parse, rules.concrete_technical_assertion,
rules.r_artifact, evidence.CorpusEvidence(evidence_dir, index, groups).evidence_for, grounding.grounding.

Output is counts and rates only. Nothing here prints or writes unit text, evidence, topic names, or
trajectory content. Uses no model and no GPU. Does not feed back into any arm.

Usage:
  nice .venv/bin/python scripts/audit_memory_quality.py              # writes results/memory-quality-audit.md
  nice .venv/bin/python scripts/audit_memory_quality.py --self-check # consistency check on 2 topic files
"""

from __future__ import annotations

import argparse
import hashlib
import re
import subprocess
import sys
import time
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE / "governor"))

from common import REPO, read_topic, topic_files  # noqa: E402
from evidence import CorpusEvidence  # noqa: E402
from grounding import concrete_tokens, grounding  # noqa: E402
from rules import concrete_technical_assertion, r_artifact  # noqa: E402
from segment import parse, reassemble  # noqa: E402

REPORT = REPO / "results" / "memory-quality-audit.md"
CODE_LINE_LIMIT = 12
RUN_V5 = REPO / "results" / "memory-generation-v5"
RUN_R25 = REPO / "results" / "memory-generation-r25"

# evidence/ exists only under the v5 run. results/memory-generation-r25/ has evidence-index.json that is
# byte-identical in content to v5's, and its evidence_file entries point at evidence/<id>.txt, so R25 reads
# v5's evidence directory and its own groups.json (the groups that built the R25 topic files).
ARMS = {
    "M2": {
        "label": "M2 (frozen-v5)",
        "memory": REPO / "memory" / "frozen-v5",
        "evidence": RUN_V5 / "evidence",
        "index": RUN_V5 / "evidence-index.json",
        "groups": RUN_V5 / "groups.json",
    },
    "M3": {
        "label": "M3 (frozen-v5-fullindex)",
        "memory": REPO / "memory" / "frozen-v5-fullindex",
        "evidence": RUN_V5 / "evidence",
        "index": RUN_V5 / "evidence-index.json",
        "groups": RUN_V5 / "groups.json",
    },
    "R25": {
        "label": "R25 (frozen-r25)",
        "memory": REPO / "memory" / "frozen-r25",
        "evidence": RUN_V5 / "evidence",
        "index": RUN_R25 / "evidence-index.json",
        "groups": RUN_R25 / "groups.json",
    },
}

_CODE_CLOSE = re.compile(r"^[ \t]{0,3}(`{3,}|~{3,})[ \t]*$")


@dataclass
class Counts:
    topic_files: int = 0
    units: int = 0
    governable: int = 0
    code_units: int = 0
    code_gt_limit: int = 0  # code units with more than 12 raw lines inside the fences
    r_artifacts: int = 0  # code units with more than 12 non-blank lines inside the fences (rules.r_artifact)
    with_resolvable: int = 0  # governable units with at least one resolvable citation
    technical: int = 0
    tech_by_method: Counter = field(default_factory=Counter)  # "cited" | "bm25" | "none"
    grounded_by_method: Counter = field(default_factory=Counter)
    grounded: int = 0
    vacuous: int = 0  # technical units with no concrete tokens (grounded vacuously)

    def add(self, other: "Counts") -> None:
        for name in ("topic_files", "units", "governable", "code_units", "code_gt_limit", "r_artifacts",
                     "with_resolvable", "technical", "grounded", "vacuous"):
            setattr(self, name, getattr(self, name) + getattr(other, name))
        self.tech_by_method.update(other.tech_by_method)
        self.grounded_by_method.update(other.grounded_by_method)


def _raw_code_lines_exceed(unit, limit: int) -> bool:
    lines = unit.lines
    closed = len(lines) >= 2 and bool(_CODE_CLOSE.match(lines[-1]))
    inner = len(lines) - 2 if closed else len(lines) - 1
    return inner > limit


def audit_topics(paths: list[Path], evidence: CorpusEvidence) -> Counts:
    counts = Counts()
    for path in paths:
        slug = path.stem
        doc = parse(read_topic(path))
        counts.topic_files += 1
        for unit in doc.units():
            counts.units += 1
            if unit.kind == "code":
                counts.code_units += 1
                if _raw_code_lines_exceed(unit, CODE_LINE_LIMIT):
                    counts.code_gt_limit += 1
            if not unit.governable:
                continue
            counts.governable += 1
            if evidence.resolvable(unit.citations):
                counts.with_resolvable += 1
            if r_artifact(unit):
                counts.r_artifacts += 1
            if not concrete_technical_assertion(unit):
                continue
            counts.technical += 1
            method, excerpts = evidence.evidence_for(unit.citations, unit.text, slug)
            ok, _missing = grounding(unit, [e.text for e in excerpts])
            key = method if method in ("cited", "bm25") else "none"
            counts.tech_by_method[key] += 1
            if ok:
                counts.grounded += 1
                counts.grounded_by_method[key] += 1
            if concrete_tokens(unit.text).count == 0:
                counts.vacuous += 1
    return counts


def check_consistency(c: Counts, label: str) -> None:
    # Assertion messages contain only numbers and the arm label, never text from the memory.
    checks = {
        "units >= governable": c.units >= c.governable,
        "governable >= technical": c.governable >= c.technical,
        "technical >= grounded": c.technical >= c.grounded,
        "technical split sums to technical": sum(c.tech_by_method.values()) == c.technical,
        "grounded split sums to grounded": sum(c.grounded_by_method.values()) == c.grounded,
        "cited technical units have resolvable citations": c.tech_by_method["cited"] <= c.with_resolvable,
        "R-artifacts are a subset of code units over the line limit": c.r_artifacts <= c.code_gt_limit,
        "code units <= units": c.code_units <= c.units,
        "vacuous <= technical": c.vacuous <= c.technical,
    }
    failed = [name for name, ok in checks.items() if not ok]
    if failed:
        raise AssertionError(f"{label}: consistency failed: {failed}")


def check_roundtrip(paths: list[Path]) -> None:
    for path in paths:
        text = read_topic(path)
        if reassemble(parse(text)) != text:
            raise AssertionError("segment reassembly is not byte-identical for a topic file")


def file_digests(folder: Path) -> dict[str, str]:
    root = folder / "topics"
    return {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in topic_files(root)}


def git_short_sha() -> str:
    try:
        out = subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=REPO, capture_output=True,
                             text=True, check=True)
        return out.stdout.strip()
    except (subprocess.CalledProcessError, OSError):
        return "unknown"


def load_evidence(spec: dict) -> CorpusEvidence:
    return CorpusEvidence(spec["evidence"], spec["index"], spec["groups"])


def pct(n: int, d: int) -> str:
    return f"{100 * n / d:.1f}%" if d else "n/a"


def frac(n: int, d: int) -> str:
    return f"{n}/{d} ({pct(n, d)})"


def arm_row(name: str, spec: dict, c: Counts | None, reason: str | None) -> str:
    if c is None:
        return f"| {spec['label']} | not computable: {reason} |"
    cited_n = c.tech_by_method["cited"]
    bm25_n = c.tech_by_method["bm25"]
    return (
        f"| {spec['label']} | {c.topic_files} | {c.units} | {c.governable} | {c.technical} "
        f"| {c.code_units} | {c.code_gt_limit} | {c.r_artifacts} "
        f"| {frac(c.with_resolvable, c.governable)} "
        f"| {frac(c.grounded_by_method['cited'], cited_n)} "
        f"| {frac(c.grounded_by_method['bm25'], bm25_n)} "
        f"| {frac(c.grounded, c.technical)} "
        f"| {c.vacuous} |"
    )


def run_self_check() -> int:
    spec = ARMS["M2"]
    paths = topic_files(spec["memory"] / "topics")[:2]
    if len(paths) < 2:
        raise SystemExit("self-check needs at least 2 topic files")
    check_roundtrip(paths)
    evidence = load_evidence(spec)
    c = audit_topics(paths, evidence)
    if c.units == 0:
        raise AssertionError("self-check: no units in the 2 topic files")
    check_consistency(c, "self-check")
    print(f"self-check ok: files={c.topic_files} units={c.units} governable={c.governable} "
          f"technical={c.technical} grounded={c.grounded}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--self-check", action="store_true")
    parser.add_argument("--out", type=Path, default=REPORT)
    args = parser.parse_args()
    if args.self_check:
        return run_self_check()

    started = time.time()
    results: dict[str, Counts | None] = {}
    reasons: dict[str, str | None] = {}

    # M3 topic files must be byte-identical to M2's; if so, M3 reuses M2's audit (topics are the audited input).
    m2_digests = file_digests(ARMS["M2"]["memory"])
    m3_digests = file_digests(ARMS["M3"]["memory"])
    m3_same_topics = m2_digests == m3_digests and len(m2_digests) > 0

    to_audit = ["M2", "R25"] if m3_same_topics else ["M2", "M3", "R25"]
    for name in to_audit:
        spec = ARMS[name]
        missing = [str(spec[k].relative_to(REPO)) for k in ("index", "groups", "evidence") if not spec[k].exists()]
        if missing:
            results[name], reasons[name] = None, f"missing {', '.join(missing)}"
            continue
        paths = topic_files(spec["memory"] / "topics")
        t0 = time.time()
        c = audit_topics(paths, load_evidence(spec))
        check_consistency(c, name)
        results[name], reasons[name] = c, None
        print(f"{name}: {c.topic_files} topic files, {c.units} units, {c.technical} technical, "
              f"{round(time.time() - t0, 1)} s", file=sys.stderr)

    if m3_same_topics:
        results["M3"], reasons["M3"] = results["M2"], None

    order = ["M2", "M3", "R25"]
    rows = [arm_row(n, ARMS[n], results[n], reasons[n]) for n in order]
    sha = git_short_sha()
    lines = [
        "# Memory-quality audit",
        "",
        "Date: 2026-10-30. Measurement only, does not feed back into any arm.",
        f"Script: `scripts/audit_memory_quality.py`. Git HEAD: `{sha}`.",
        "Counts and rates only. No memory, lesson, topic or trajectory text is reported.",
        "",
        "| Arm | Topic files | Units | Governable | Technical | Code units | Code >12 lines | R-artifacts "
        "| Resolvable-cited share (governable) | Grounded, cited evidence | Grounded, BM25 evidence "
        "| Grounded, all technical | Vacuous technical |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
        *rows,
        "",
        "Notes:",
        "- Units = all parsed units, headings included. Governable = non-heading units. Technical = governable "
        "units where `rules.concrete_technical_assertion` holds. Code >12 lines counts raw lines inside fences; "
        "R-artifacts use the non-blank rule in `rules.r_artifact`.",
        "- Grounding is the A2 rule (`grounding.grounding`) over all technical units, including R-artifact code "
        "blocks. Evidence is the cited steps when citations resolve, otherwise the top-3 BM25 steps in the topic's "
        "group. Vacuous = technical units with no concrete tokens, counted as grounded.",
        (f"- M3 topic files are byte-identical to M2's ({len(m2_digests)} files, same names and SHA-256 digests), so M3 "
         "reuses the M2 audit and is not recounted. Only MEMORY.md differs (M3 has the appended complete index).")
        if m3_same_topics else
        "- M3 topic files differ from M2's; M3 was not audited separately (see table).",
        "- R25 evidence: `results/memory-generation-r25/` has no `evidence/` directory. Its `evidence-index.json` "
        "matches v5's content, so R25 reads `results/memory-generation-v5/evidence/` with its own `groups.json`.",
        f"- Runtime: {round(time.time() - started, 1)} s.",
    ]
    args.out.write_text("\n".join(lines) + "\n", encoding="utf-8")

    # stdout: counts only.
    for name in order:
        c = results[name]
        if c is None:
            print(f"{name}: not computable ({reasons[name]})")
        else:
            print(f"{name}: files={c.topic_files} units={c.units} governable={c.governable} "
                  f"technical={c.technical} cited={c.tech_by_method['cited']} bm25={c.tech_by_method['bm25']} "
                  f"none={c.tech_by_method['none']} grounded={c.grounded} vacuous={c.vacuous}")
    print(f"wrote {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
