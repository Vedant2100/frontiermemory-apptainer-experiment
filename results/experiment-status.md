# FrontierMemory one-task exploratory result

Date: 2026-10-24 (Slurm logs in UTC may roll over to 2026-10-25)

## Result

One official FrontierMemory v1.0 task, `awilix-release-tier-implicit`, was run sequentially in Harbor 0.24.0 with Mini-SWE-Agent 2.4.6 and the same local Ollama Qwen2.5-Coder 7B Q4 model. A and B used the same task image, task instructions, verifier, model, temperature, and 50-call Mini-SWE limit. B additionally received a small memory generated before the target task was downloaded.

| Condition | Memory | Original verifier | Model calls / bash actions | Prompt tokens | Completion tokens | Agent time | Whole trial time |
|---|---|---:|---:|---:|---:|---:|---:|
| A | None | **Fail (0.0)** | 50 / 49 | 196,352 | 962 | 78.9 s | 134.2 s |
| B | Corpus-derived memory | **Fail (0.0)** | 50 / 49 | 311,123 | 1,164 | 51.3 s | 106.2 s |

Whole trial time includes environment setup, agent run, and verifier. Both conditions stopped at the same explicit 50-model-call limit (`LimitsExceeded`). Harbor and Ollama reported $0 model cost; inference stayed local.

The agent behaved differently but did not solve the task. A used 24 `cat src/container.ts` and 23 `cat src/resolvers.ts` calls; B used 44 repeated `grep -n 'initialize' src/container.ts` calls. Neither produced the implementation/version change required by the verifier. The original verifier wrote reward `0`; its TypeScript suite also failed because the requested `.initializer` and `.initialize` APIs were absent. The generated memory therefore changed tool selection and increased prompt-token use, but did not improve pass/fail on this task.

## Method and limits

- Historical input: official gated FrontierMemory v1.0 corpus at revision `67250357405072066498c061f9af0eccfdac20c0`, digest `c7d31214ed20af4f14f46c4b9a838ebc9aa35a9491dfbce0fa50f7aa456eedd1`. The memory process ran before the target task was downloaded or inspected.
- The memory summarizes command-frequency metadata from 100 Mini-SWE histories plus a small deterministic sample; it is weak frequency-based workflow memory, not full semantic synthesis of trajectories. Corpus filenames have no task mapping, and frequency does not establish causation.
- The target task and original verifier were not edited. Their downloaded source hashes are in `target-task-source-sha256.txt`. Harbor needed a local staging copy that points to Apptainer SIFs and uses public network modes. Harbor's Singularity backend cannot enforce the task's original no-network policy, so egress isolation was not guaranteed. A and B share this adaptation.
- The task's `tests/Dockerfile` uses a separate verifier image. Its original pinned base and test files were reproduced in an Apptainer SIF; Harbor's FastAPI/Uvicorn runtime dependencies were added to that image. The original `tests/test.sh` executed in both conditions.
- The generated memory, gated corpus, official task files, task verifier, model weights, raw trajectories, and raw logs remain in local storage and are not included in a GitHub publication. The gate does not permit republishing the corpus outside its gated repository; the small memory is treated as derived gated content too.

Detailed setup failures, adaptations, and job IDs are in `history.md`.
