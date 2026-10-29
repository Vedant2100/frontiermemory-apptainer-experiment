"""Evidence retrieval for the governor (preregistration v1, section 2.3).

Inputs are only the corpus evidence that build_corpus_evidence_v5.py produced for memory v5:
  results/memory-generation-v5/evidence-index.json   (per trajectory: id, outcome, step ids)
  results/memory-generation-v5/evidence/<id>.txt      (condensed steps, "--- step=K role=R" blocks)
  results/memory-generation-v5/groups.json           (topic slug -> trajectory ids)

No task data, verifier, or trial result is read. The only labels used are the PASS/FAIL
outcomes that the v5 evidence index already records for each trajectory.

Rules:
- A unit with at least one resolvable citation (`inputs/tNNNN.json#step=K` where tNNNN is in the
  index and K is one of its step ids) gets exactly those cited steps, in citation order.
- Otherwise the unit gets the top-3 steps by BM25 (k1=1.5, b=0.75) over every step of every
  trajectory in its topic's group. The query is the unit text with citations removed.
  Ties are broken by (trajectory id, step). BM25 IDF is ln(1 + (N - n + 0.5) / (n + 0.5)).
- Each step is truncated to 2,000 characters for the judge, and each excerpt carries the
  trajectory's recorded outcome (PASS or FAIL).
"""

from __future__ import annotations

import json
import math
import re
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

from segment import CITATION

STEP_CAP = 2000
TOP_K = 3
BM25_K1 = 1.5
BM25_B = 0.75
TOKEN = re.compile(r"[a-z0-9]+")
BLOCK_HEADER = re.compile(r"^--- step=(\d+) role=(.*)$")


@dataclass
class Step:
    trajectory: str
    step: int
    role: str
    outcome: str
    body: str  # full step text (used for scoring)


@dataclass
class Excerpt:
    trajectory: str
    step: int
    role: str
    outcome: str
    text: str  # truncated to STEP_CAP for the judge
    truncated: bool
    source: str  # "cited" or "bm25"


def tokenize(text: str) -> list[str]:
    return TOKEN.findall(text.lower())


def strip_citations(text: str) -> str:
    return CITATION.sub(" ", text)


def parse_steps(evidence_text: str) -> dict[int, tuple[str, str]]:
    """Map step id -> (role, body) from a condensed evidence file."""
    steps: dict[int, tuple[str, str]] = {}
    current: int | None = None
    role = ""
    buf: list[str] = []

    def flush() -> None:
        if current is not None:
            steps[current] = (role, "\n".join(buf).strip("\n"))

    for line in evidence_text.split("\n"):
        header = BLOCK_HEADER.match(line)
        if header:
            flush()
            current, role, buf = int(header.group(1)), header.group(2), []
        elif current is not None:
            buf.append(line)
    flush()
    return steps


class BM25Index:
    """BM25 over one group's steps. Documents are the steps of the group's trajectories."""

    def __init__(self, docs: list[tuple[str, int, list[str]]]):
        self.keys = [(tid, step) for tid, step, _ in docs]
        self.tokens = [toks for _, _, toks in docs]
        self.n = len(docs)
        self.lengths = [len(t) for t in self.tokens]
        self.avgdl = (sum(self.lengths) / self.n) if self.n else 0.0
        self.tf = [Counter(t) for t in self.tokens]
        self.df: Counter = Counter()
        for counts in self.tf:
            self.df.update(counts.keys())

    def idf(self, term: str) -> float:
        n_q = self.df.get(term, 0)
        return math.log(1.0 + (self.n - n_q + 0.5) / (n_q + 0.5))

    def top(self, query_tokens: list[str], k: int) -> list[int]:
        terms = sorted(set(query_tokens))
        scores = [0.0] * self.n
        for term in terms:
            idf = self.idf(term)
            if idf <= 0:
                continue
            for i, counts in enumerate(self.tf):
                f = counts.get(term, 0)
                if not f:
                    continue
                norm = 1 - BM25_B + BM25_B * (self.lengths[i] / self.avgdl if self.avgdl else 0.0)
                scores[i] += idf * f * (BM25_K1 + 1) / (f + BM25_K1 * norm)
        ranked = [i for i in range(self.n) if scores[i] > 0]
        ranked.sort(key=lambda i: (-scores[i], self.keys[i][0], self.keys[i][1]))
        return ranked[:k]


class CorpusEvidence:
    def __init__(self, evidence_dir: Path, index_path: Path, groups_path: Path):
        self.evidence_dir = evidence_dir
        index = json.loads(index_path.read_text(encoding="utf-8"))
        self.files = {f["id"]: f for f in index["files"]}
        groups = json.loads(groups_path.read_text(encoding="utf-8"))["groups"]
        self.group_ids = {g["slug"]: list(g["ids"]) for g in groups}
        self._steps: dict[str, dict[int, tuple[str, str]]] = {}
        self._bm25: dict[str, BM25Index] = {}

    def available(self, tid: str) -> set[int]:
        """Steps present in the evidence file. Truncated trajectories omit some step ids."""
        entry = self.files[tid]
        return set(entry["step_ids"]) - set(entry.get("omitted_steps", []))

    def trajectory_steps(self, tid: str) -> dict[int, tuple[str, str]]:
        if tid not in self._steps:
            text = (self.evidence_dir / f"{tid}.txt").read_text(encoding="utf-8")
            parsed = parse_steps(text)
            if set(parsed) != self.available(tid):
                raise ValueError(f"{tid}: parsed step ids differ from evidence index")
            self._steps[tid] = parsed
        return self._steps[tid]

    def _step(self, tid: str, step: int) -> Step:
        role, body = self.trajectory_steps(tid)[step]
        return Step(tid, step, role, self.files[tid]["outcome"], body)

    def resolvable(self, citations: list[tuple[str, int]]) -> list[tuple[str, int]]:
        out: list[tuple[str, int]] = []
        seen: set[tuple[str, int]] = set()
        for name, step in citations:
            tid = name.split(".")[0]
            if tid not in self.files or step not in self.available(tid):
                continue
            if (tid, step) not in seen:
                seen.add((tid, step))
                out.append((tid, step))
        return out

    def _group_index(self, slug: str) -> BM25Index:
        if slug not in self._bm25:
            docs: list[tuple[str, int, list[str]]] = []
            for tid in self.group_ids.get(slug, []):
                for step in sorted(self.trajectory_steps(tid)):
                    docs.append((tid, step, tokenize(self._step(tid, step).body)))
            self._bm25[slug] = BM25Index(docs)
        return self._bm25[slug]

    def _excerpt(self, step: Step, source: str) -> Excerpt:
        text = step.body
        truncated = len(text) > STEP_CAP
        return Excerpt(
            trajectory=step.trajectory,
            step=step.step,
            role=step.role,
            outcome=step.outcome,
            text=text[:STEP_CAP],
            truncated=truncated,
            source=source,
        )

    def evidence_for(self, citations: list[tuple[str, int]], unit_text: str, slug: str):
        """Return (method, excerpts). method is 'cited', 'bm25', or 'none'."""
        cited = self.resolvable(citations)
        if cited:
            return "cited", [self._excerpt(self._step(t, s), "cited") for t, s in cited]
        index = self._group_index(slug)
        if index.n == 0:
            return "none", []
        query = tokenize(strip_citations(unit_text))
        picked = index.top(query, TOP_K)
        excerpts = []
        for i in picked:
            tid, step = index.keys[i]
            excerpts.append(self._excerpt(self._step(tid, step), "bm25"))
        return ("bm25" if excerpts else "none"), excerpts
