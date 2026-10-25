# FrontierMemory Awilix task: OpenCode + local Qwen3-Coder 30B

Date: 2026-10-25. One-task exploratory evaluation; not a leaderboard submission.

## Result

Both runs used Harbor 0.24.0's built-in OpenCode 1.19.4 adapter, Ollama 0.40.11, and the same official `awilix-release-tier-implicit` task and original verifier. The task checksum in both Harbor result records matches. The persistent Ollama model was `qwen3-coder:30b`, Q4_K_M, served on a 24 GB RTX 3090. `/api/ps` repeatedly reported an actual loaded context of 32,768 tokens (about 21.7 GB VRAM occupied). A and B used the same model/context and OpenCode settings; B additionally received generated historical memory.

| Measure | A: no memory | B: historical memory |
|---|---:|---:|
| Pass/fail | Fail — reward 0.0 (functional 0, preference 0) | Fail — reward 0.0 (functional 0, preference 0) |
| OpenCode steps | 53 | 52 |
| Agent behavior | 21 shell calls; 9 edit/write calls; source and test files changed | 11 shell calls; 10 edit calls; partial resolver/container changes |
| Agent test/build commands | 6 attempted; none passed | None before stop |
| OpenCode processed tokens | 902,325 total; 7,921 output | 880,043 total; 11,872 output |
| Agent elapsed time | 5m29s | 7m33s |
| Harbor condition runtime | 6m15s | 8m50s, including verifier and collection |

Token totals are sums of OpenCode step records and include cached prompt tokens; they are not unique prompt lengths. A's test/build attempts failed on TypeScript errors, including errors in the new initializer/resolver types and a package test configuration error. The unchanged original verifier returned zero for both functional behavior and the release preference. A made implementation edits but did not satisfy either verifier component. B was manually interrupted after four consecutive failed insertions of its main `container.ts` implementation. Harbor recorded a nonzero agent exit, collected the partial patch and trajectory, and still ran the original verifier, which returned zero. B did not reach agent tests.

The B memory was generated after A showed source implementation progress, using only the pre-existing evidence-backed historical-corpus summary. The generation request did not contain the target prompt, target verifier, or this run's debugging history. It produced a 5,595-byte memory artifact in 35.5 seconds with the same local model. The generated memory and its corpus-derived source remain excluded from GitHub.

The measured behavior differed, but both conditions scored zero and B ended early. This is not evidence that memory helped or hurt; the experiment does not support a causal conclusion.

## Cluster and nonstandard setup

The initial OpenCode run (`299049`) did not reach Ollama. Its diagnostics showed a failed `models.dev` DNS lookup and `Model not found: ollama/qwen3-coder:30b`: Harbor placed the provider file outside OpenCode's active isolated config directory. Supplying `OPENCODE_CONFIG_CONTENT` and disabling model discovery fixed local model resolution. A 16K-context retry still looped on reads without edits. The completed A/B run used a verified 32K context on the smaller RTX 3090; the 30B Q4 model fit, so switching to the 7B fallback was unnecessary.

Harbor ran the task through Apptainer's Singularity backend and reused the existing task and verifier images. The backend rejects the task's `no-network` setting, so the local staging copy used Harbor's accepted public network mode for both conditions; the downloaded source task and original verifier were left unchanged, but shell egress was not isolated. This is a nonstandard exploratory evaluation.

Raw task data, verifier details, trajectories, patches, model logs, and corpus-derived memory remain in ignored local run directories. The repository contains the experiment code and sanitized aggregate results only.
