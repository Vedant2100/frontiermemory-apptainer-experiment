# FrontierMemory Apptainer exploratory experiment

A one-task A/B comparison of Mini-SWE-Agent with and without learned workflow memory, run locally on a Slurm GPU cluster. This is an exploratory run, not a leaderboard result.

## Result

| Condition | Memory | Original verifier | Model calls / shell actions | Input / output tokens | Agent time | Whole trial |
|---|---|---:|---:|---:|---:|---:|
| A | None | **Fail (0.0)** | 50 / 49 | 196,352 / 962 | 78.9 s | 134.2 s |
| B | Official-corpus-derived memory | **Fail (0.0)** | 50 / 49 | 311,123 / 1,164 | 51.3 s | 106.2 s |

Both runs used the same local Qwen2.5-Coder 7B Q4 model, Mini-SWE-Agent 2.4.6, task image, task, verifier, and 50-call limit. B changed tool behavior: A mostly alternated between reading two source files, while B repeated a search for `initialize`. Neither solved the task. The memory increased prompt tokens without changing verifier outcome.

Full sanitized metrics are in [`results/paired-metrics.csv`](results/paired-metrics.csv), and the run summary is in [`results/experiment-status.md`](results/experiment-status.md). Detailed cluster and troubleshooting history is in [`results/history.md`](results/history.md).

## Setup and deviations

- Cluster: Slurm, Apptainer 1.5.2, NVIDIA RTX 2080 Ti with 10.6 GiB VRAM. Docker was unavailable; Harbor 0.24.0's Singularity backend was invoked through `bin/singularity`.
- Model: Qwen2.5-Coder 7B Q4 in persistent cluster storage. The preferred 14B allocation had an approximately eight-hour queue estimate, so the user-approved 7B fallback was used. Inference used local Ollama 0.40.11; no paid API was used.
- Data: official FrontierMemory v1.0 gated corpus, pinned to revision `67250357405072066498c061f9af0eccfdac20c0`. The target task was not downloaded or inspected until memory generation had finished.
- Memory: generated with the same local 7B model from aggregate/command-frequency evidence. It is a weak frequency summary, not semantic synthesis of complete trajectories; opaque corpus filenames cannot be mapped to source tasks, and command frequency does not show causation.
- Harbor's Apptainer backend cannot enforce the task's original `no-network` policy. A local staging copy used `public` network modes so Harbor would run; egress isolation was not guaranteed. Both A and B used this same nonstandard setup and had only the local model endpoint configured.
- The official task and verifier files were left unchanged. Their container images were adapted to Apptainer SIFs from the pinned Docker bases. The separate verifier SIF contains the files from the official `tests/Dockerfile` plus FastAPI/Uvicorn needed by Harbor.
- Mini-SWE-Agent defaults to unlimited steps. Both conditions were given the same 50-model-call limit after an unbounded pilot repeated source reads; both hit the cap. The original verifier still ran and returned reward 0.0 for each.

## Reproduction outline

The gated benchmark source and model weights are not distributed here. Obtain access to the official FrontierMemory v1.0 corpus and Harbor task data through their original sources, then reproduce the phase order:

1. Install FrontierMemory, Harbor, Ollama, and Mini-SWE-Agent in the cluster environment. Provision Apptainer SIFs and the Python 3.12 agent runtime using the definitions and scripts in `containers/`, `runtime` (created locally), and `slurm/`.
2. Fetch only the pinned historical v1.0 corpus and generate memory before downloading the target task. The local implementation is `scripts/summarize_frontiermemory_corpus.py` plus `scripts/generate_memory_from_evidence.py`.
3. Download the official task and use `containers/awilix-release-tier-implicit.def`, `containers/awilix-release-tier-implicit-serverdeps.def`, and `containers/awilix-release-tier-implicit-verifier.def` to build the Apptainer images. The task staging copy must point the agent and separate verifier environments to their respective SIFs.
4. Prepare B's config locally with the gated-derived memory:

   ```bash
   python scripts/render_memory_config.py --memory /path/to/local/MEMORY.md
   ```

   The generated `configs/mini-swe-ollama-7b-memory.yaml` is intentionally ignored by Git.
5. Run the paired Slurm script with `sbatch slurm/run-awilix-ab.sbatch`. Update its cluster-specific absolute paths if installing elsewhere. It starts Ollama once and runs A then B sequentially.

Raw gated corpus files, task/verifier files, derived memory, model weights, raw trajectories, tool runtimes, and unfiltered logs are intentionally excluded from this repository. They remain in the local experiment workspace under the relevant access restrictions.
