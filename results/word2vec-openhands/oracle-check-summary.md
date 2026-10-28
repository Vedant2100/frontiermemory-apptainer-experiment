# Word2Vec oracle and nop collection check (Slurm job 301906)

Date: 2026-10-27. CPU-only (`batch` partition, 4 CPUs, 16G). No model, Ollama, or GPU.
Harbor 0.24.0, Apptainer 1.5.2, Python 3.10 verifier image, Python 3.12 agent runtime.
Task `letta-ai/build-word2vec-pipeline`, staged fresh per trial. Verifier test-file hashes
matched the pinned source. Verifier network mode staged as `public` (egress isolation not
enforced, as in the protocol).

Slurm: `COMPLETED`, exit `0:0`, elapsed 00:01:32.

| Trial | Agent | Declared artifact present | Cases collected | Cases passed | Collection error | Reward | Trial wall time | Status |
|---|---|---|---|---|---|---|---|---|
| oracle | `oracle` | yes | 6 | 6 | no | 1 | 42 s | PASS |
| nop | `nop` | no | 0 | 0 | yes (1 error during collection) | 0 | 37 s | INVALID (zero collected cases) |

Gate (Phase 1): PASS. The oracle trial produced the artifact, collected 6 cases, passed all 6, and
got reward 1. The nop trial confirms that a missing `/workspace/solution.py` yields zero collected
cases, so it is scored as INVALID rather than 0.

Resubmissions: none (1 of 3 allowed Slurm jobs used).

Raw outputs (Harbor trials, workspaces, logs, and staged task copies) remain local and
git-ignored under `results/word2vec-openhands/oracle-check-301906/`.
