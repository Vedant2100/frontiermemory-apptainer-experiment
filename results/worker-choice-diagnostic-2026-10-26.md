# No-memory worker diagnostic: compaction, task scope, and frontier model

Date: 2026-10-26. Exploratory diagnostics only; no memory comparison or leaderboard claim.

## Results

| Run | Model and harness | Actual work | Verification and time |
| --- | --- | --- | --- |
| A: no compaction, cattrs | Qwen3-Coder 30B Q4_K_M; OpenCode 1.19.4 via Harbor 0.24.0 and Ollama 0.40.11; RTX 3090 | Loaded context was 32,768 tokens. With `compaction.auto=false` in both OpenCode config paths, the agent made 3 tool calls (glob and 2 reads), no edits, and no test attempts. Peak recorded prompt was 23,167 tokens; the common safety watcher stopped before context overflow. | Original verifier: 0/70 functional, 7/7 preference, reward 0. Agent 20s; Harbor trial 1m07s; Slurm job 2m27s. Ollama reported 36,107 input tokens (19,367 cached) and 110 output tokens. |
| C: alternate task, no memory | Same Qwen/OpenCode/Ollama setup and 32K loaded context; official `awilix-release-tier-implicit` task | 4 inspection calls, no edits or test attempts. Peak prompt 19,682 tokens; same watcher stopped the run. | The staged collector initially included Harbor runtime files, so its 0 reward is not a valid task score. Agent 16s; Harbor trial 1m39s; Slurm job 2m07s. Ollama reported 47,221 input tokens (27,541 cached) and 97 output tokens. |
| B: frontier worker, no memory | Codex CLI `gpt-6-astra`, ephemeral workspace-write; fresh Awilix checkout at the task's pinned base | Completed in 16m58s with 26 command executions and 7 file-change events. It made an 8-file, 939-addition/102-deletion patch and added 20 focused tests; its fallback smoke runner passed 20/20. Usage: 1,150,195 input tokens (1,100,928 cached), 26,759 output (10,797 reasoning). | Final-patch replay reached Rollup but failed because `container.ts` references an undefined `util`; original functional tests did not execute. Functional 0, preference 0/1, strict reward 0. The implementation did not pass the task. |

## Interpretation

Disabling compaction did not get Qwen3-Coder 30B to implementation. It continued to inspect large files, then hit the same context-safety stop. Moving to a different official task did not change that behavior. These runs do not prove compaction has no effect, because they are not a matched compaction-on/off pair, but compaction alone is not a sufficient fix.

The frontier Codex worker made sustained implementation progress, unlike the Qwen/OpenCode runs, but its first patch did not type-check. This points to model capability or implementation reliability as a substantial remaining bottleneck. The result is diagnostic, not causal: the model and harness changed, and the Codex run was not executed on the cluster GPU.

The OpenCode prompt-token totals are cumulative usage across calls; cached tokens are included in those input totals. No new memory was generated or supplied in any run. The original task and verifier sources were not edited.

## Verifier replay and nonstandard details

- The first direct replay could not clone the Codex checkout because it is a shallow partial clone whose promisor remote was unavailable. A local filesystem copy avoided that fetch. An interim patch was replayed while the Codex CLI was still working; that result is superseded and not counted. The final replay used the completed patch, and no verifier output was fed back to the agent.
- The verifier SIF lacked the task project's preinstalled npm tools. I reused `node_modules` from the already-built task SIF (216 MB) and bind-mounted it into the existing verifier SIF. The verifier's original `test.sh` and `original-test.sh` remained unchanged, as did the task files. This dependency bind is a nonstandard replay detail.
- An initial replay with the task SIF failed because that image lacks the `agent` account required by the verifier wrapper. The final replay used the verifier SIF, preserving its `agent` user and test scripts.
- The Codex attempt used no memory and did not see verifier output while generating its patch. The held-out preference target is omitted from this report. Raw trajectories, patches, and verifier logs remain local.

## Recommendation

Keep the no-compaction Qwen configuration as a recorded diagnostic, not the preferred worker. Do not spend another run on the same Qwen/OpenCode inspection loop or start a memory A/B from these results. A stronger model did reach implementation, but first needs a separate reliable baseline that passes the unchanged verifier. The 48K/64K context and preserved-recent-token compaction variants were not tested here.
