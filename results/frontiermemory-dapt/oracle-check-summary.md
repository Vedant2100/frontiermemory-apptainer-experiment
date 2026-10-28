# DAPT intrusion-detection oracle and nop collection check (Slurm job 302130)

Date: 2026-10-28. CPU-only (`batch` partition, 4 CPUs, 16G). No model, Ollama, or GPU.
Task `letta-ai/dapt-intrusion-detection-workflow-learning` (SkillsBench v1.1 source), staged fresh per trial.
Harbor 0.24.0, Apptainer 1.5.2, Ubuntu 24.04 agent image (Python 3.12.3), verifier image Python 3.12.3 with pytest 8.4.1 and pytest-json-ctrf 0.3.5.

Task contract (from `task.toml` and `instruction.md`):
- Declared artifact: `/root/network_stats.csv`. Agent working directory: `/root` (from the Dockerfile `WORKDIR`).
- Agent timeout: 5400 s. Verifier timeout: 600 s. Harbor multiplier 1.0.
- No workspace mount is needed: Harbor downloads the artifact from the agent container and uploads it to the verifier container at the same absolute path (`artifacts/root/network_stats.csv`).

| Trial | Agent | Harbor exit | Declared artifact | Cases collected | Cases passed | Reward | Agent time | Verifier time | Status |
|---|---|---|---|---|---|---|---|---|---|
| oracle | `oracle` | 0 | present (`ok`) | 37 | 37 | 1 | ~35 s | ~16 s | PASS |
| nop | `nop` | 0 | present (template, unchanged) | 37 | 0 (37 failed) | 0 | <1 s | ~16 s | PASS (expected reward 0) |

Gate (CPU check): PASS. Oracle reward 1 with all verifier cases passing, nop reward 0.

Staging and preflight:
- Staging helper: `scripts/stage_word2vec_task_for_apptainer.py` (generic; it rewrites only `docker_image` and the verifier network mode in a copy of `task.toml`). Verifier network mode staged as `public`; the official value is `no-network`, which Harbor's Singularity backend rejects. Egress isolation is not enforced in this Apptainer evaluation.
- Verifier test-file SHA-256 inside the verifier image matches the pinned task source (hashes only; the test files were not read).
- The verifier image is built from the agent image plus pytest and pytest-json-ctrf, not from the official `tests/Dockerfile`. That Dockerfile was not read, per the handling rules, so its base and dependencies could not be mirrored exactly.
- The agent image is a conversion of `environment/Dockerfile` (same pinned Ubuntu digest, same apt and pip pins, same `/root` COPY targets).

Images (local, git-ignored):
- `containers/frontier-memory-dapt-agent.sif`, 134 MB, built from `containers/frontier-memory-dapt-agent.def`.
- `containers/frontier-memory-dapt-verifier-v2.sif`, about 138 MB, built from `containers/frontier-memory-dapt-verifier-v2.def`. It is the image used by the passing run.
- `containers/frontier-memory-dapt-verifier.sif` (v1, about 138 MB) lacked the `--ctrf` pytest plugin, so its verifier failed before any case ran. It is kept for the record only.

Failed attempts before the gate passed (no resubmission hidden):
- Job 302126 (build on `batch`): failed at 12 s because compute-node DNS could not resolve `auth.docker.io`. Images were built on the login node instead, with the same script.
- Job 302129 (check with verifier v1): Harbor exit 0, but both trials scored reward 0 because the verifier invoked pytest with `--ctrf`, which the v1 image did not provide. Those scores are invalid. The v2 verifier image fixed it.

Slurm: job 302130 `COMPLETED`, exit `0:0`, elapsed 00:02:00.

Raw outputs (Harbor trials, verifier logs, staged task copies, and the original-task SHA-256 check) stay local and are git-ignored under `results/frontiermemory-dapt/oracle-check-*/`.
