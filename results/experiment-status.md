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

## Latest OpenCode runner check (2026-10-26)

The cattrs no-memory A trace failed on repeated exact-match edit errors; the historical-memory B trace ended normally after returning pseudo-tool markup as plain text, before editing. The shared prompt now directs both conditions to use current file contents and recover mismatched edits through `write` or Bash/Python. A Harbor canary on the existing 30B/A5000 setup produced two new files, passed 4/4 tests, yielded a clean 1,112-byte patch, and passed its separate canary verifier. This is a runner check only; no new FrontierMemory A/B run or leaderboard result is claimed. Details: `additional-opencode-frontiermemory-evaluation.md`.

## Additional diagnostic experiments and stronger memory candidates

| Run | Setup | Result | Interpretation |
|---|---|---|---|
| Terminus-2 no-memory, 298869 | Harbor 0.24, local Qwen2.5-Coder 7B Q4, RTX 2080 Ti | Setup exception before model call: task SIF lacked tmux; package installation could not reach the network. | Infrastructure failure, not an agent result. |
| Terminus-2 no-memory, 298878 | Same task/model/node; host tmux bound read-only into the Apptainer agent container; recording disabled | Early-stopped after 9 turns and 18 shell actions. Repeated `ls -la` 9 times and an unresolved placeholder `cd` 8 times. 38,422 prompt / 1,882 completion tokens. No useful edits, tests, or verifier run. | Terminus-2 with the same 7B model also looped. This argues against Mini-SWE-Agent being the sole cause, but does not isolate model from parser/harness behavior. |
| OpenCode smoke, 298840 | OpenCode without Harbor, Qwen3-Coder 30B Q4, RTX 6000 Ada | The user reported that the smoke test made a real code change and passed tests. | Smoke-test success permitted the Harbor follow-up; the smoke artifacts are outside this experiment workspace. |
| OpenCode + Awilix no-memory, 299049 | Harbor's OpenCode 1.19.4 adapter, Ollama Qwen3-Coder 30B Q4, RTX 6000 Ada | OpenCode returned an internal server error before any Ollama inference request. No assistant turn, tool call, source edit, or agent test. The unchanged original verifier ran and returned reward 0.0. | No valid A/B result. The verifier's functional and release-preference rewards were both 0.0 on the unchanged baseline; actual model context was not loaded or verified. B was skipped. See [`opencode-awilix-status.md`](opencode-awilix-status.md). |

The Terminus job used the official task through the existing local Apptainer staging copy and did not modify benchmark task/verifier files. Its first attempt confirmed that Harbor's default Terminus setup tries to install tmux/asciinema inside the SIF; the second used a read-only host-tool bind and successfully began agent turns. Full trial details and limits are in `results/terminus2-awilix-298878-status.txt` and `history.md`.

The CPU corpus review produced 14 human-curated, evidence-backed memory candidates from 10 successful Mini-SWE ATIF trajectories. The local artifact is `data/evidence-backed-memories.md`; it is intentionally Git-ignored because the official corpus card restricts republishing corpus derivatives outside its gated repository. The filter excluded two raw corpus files matching the user-supplied evaluation task/repository markers before parsing. The corpus has no filename-to-task mapping, so semantic overlap beyond those marker matches cannot be ruled out. The review used no model and makes no causal/pass-rate claim.
