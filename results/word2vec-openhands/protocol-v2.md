# Word2Vec OpenHands memory experiment: protocol v2

Date: 2026-10-27. Supersedes the informal Word2Vec plan behind the paired run in
`paired-evaluation-20261027.md`. Gated corpus, task, and verifier contents are not
reproduced here.

## Decisions

- **D1 (scope).** Single task: `letta-ai/build-word2vec-pipeline`. The Awilix,
  cattrs, and cookie-store tasks are dropped because the corpus holds only about
  0-3 related trajectories each. APEX is excluded because its judge is a paid LLM.
- **D2 (memory v2).** Regenerate memory from the pinned `joint-674-v1.0` corpus
  using family-selected evidence: the 14 trajectories whose instruction text
  mentions word2vec (3 PASS, 11 FAIL), excluding incidental mentions. The previous
  generator (`slurm/run-word2vec-memory-generation.sbatch`, line 49) excluded every
  word2vec/gensim/nltk trajectory. That is stricter than `docs/rules.md`, which only
  forbids giving the memory agent the target tasks, their verifiers, the repo, or
  answers, and it produced the weak memory. Disclosed deviation: family-targeted
  evidence selection replaces a 6-hour whole-corpus dream agent. The question is
  "given relevant history, does memory help this local agent?"
- **D3 (budget).** Raise OpenHands `max_iterations` to 200 so the task.toml agent
  timeout (1200 s) is the binding limit. Pin reasoning effort explicitly and
  identically in both arms.
- **D4 (design).** k=3 trials per arm, one Slurm job, order A B B A A B, a fresh
  task copy for each trial, one shared model server.
- **D5 (metric).** Primary: verifier test cases passed / collected. Secondary: strict
  pass. Zero collected cases makes a trial INVALID, never a score of 0.

## Gates

- **Phase 1:** oracle collection check. The oracle solution must produce the
  declared artifact and the verifier must collect and pass all cases.
- **Phase 2:** memory relevance audit. At least 3 concrete, cited Word2Vec-applicable
  lessons, frozen with a sha256.
- **Phase 3:** one no-memory smoke run must create `/workspace/solution.py`, and the
  verifier must collect at least one case. The pre-declared single fallback model is
  Qwen3-Coder 30B (cached), used only if Qwen3.8 fails the smoke test twice.
- **Phase 4:** A/B run under the D4 design.
- **Early stop:** a trial that repeatedly searches the environment or system without
  making edits is marked INVALID.

## Fixed configuration

- Model: `qwen3.8:27b-mtp-q4_K_M`, temperature 0.1, 65,536-token context.
- OpenHands SDK 1.58.2, Harbor 0.24.0, Ollama 0.40.11, Apptainer 1.5.2.
- No GPU for Phase 1 (CPU Slurm job only). No Docker.

## Known nonstandard limitation

Harbor's Singularity backend cannot enforce no-network. Staging therefore sets the
verifier `network_mode` to `public` on the disposable task copy only. Egress
isolation is not enforced, and every result must say so.
