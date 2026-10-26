# FrontierMemory cattrs OpenCode pair on RTX 3090

Date: 2026-10-26

Starting repository revision: `81c5bf8`

Task: official FrontierMemory v1.0 `cattrs-compositional-changelog`

Task checksum in both Harbor trials: `45fda195e6d9582d36a1a3c7e07fb11a6a33b4932085cb9946415410afa05280`

This was one exploratory pair, not a leaderboard submission. The task and its original verifier were not modified. Raw prompts, patches, trajectories, verifier files, corpus data, and generated memory stay local and are excluded from this report.

## Controls

- Harbor 0.24.0 OpenCode adapter, OpenCode 1.19.4, Ollama 0.40.11, Apptainer 1.5.2, and `qwen3-coder:30b` were used in both conditions.
- Both jobs ran sequentially on RTX 3090 node `nodevcggpu02`. Ollama `/api/ps` recorded the loaded model at a 32,768-token context in both runs.
- Both used the same official task checksum, staged task/verifier images, base prompt, settings, and repetition watcher. The rendered prompt diff showed only the historical-memory block added in B.
- B used the frozen historical memory with SHA-256 `0b97695a6643b962f66db830aa597c29551744a01896023581a0b9c1c6275797`.
- Harbor's Singularity backend does not enforce the task's `no-network` setting; this evaluation used its available public network mode. No network-isolation claim is made.
- Raw result artifacts remain in ignored local `jobs/` and `results/opencode-frontiermemory-tasks/` directories.

## Results

| Condition | Original verifier | Agent work | OpenCode steps / tool calls | Input / cached / output tokens | Agent time / Harbor trial | Termination |
|---|---|---|---:|---:|---:|---|
| A, no memory (Slurm `300310`) | Reward 0; functional 18/70; preference 7/7; partial 0.3247 | Nonempty 14,968-byte patch. `py_compile` passed and `tests/test_baseconverter.py` passed 10/10. An added smoke test found implementation errors during the run. | 48 / 45 | 712,730 / 615,563 / 13,891 | 600.0 s / 675.2 s | Singularity's command HTTP request timed out after 600 s; Harbor recorded `AgentTimeoutError`. The separate original verifier still ran and scored the collected patch. |
| B, frozen memory (Slurm `300312`) | Reward 0; functional 0/70; preference 7/7; partial 0.0909 | Empty patch; no code edit or test run. | 19 / 15 | 232,301 / 93,471 / 2,573 | 162.3 s / 203.6 s | The shared watcher interrupted OpenCode after the same `read` operation/output repeated four times in the last ten calls (exit 130). Harbor then ran the original verifier against the empty patch. |

Times are agent execution and whole Harbor trial, respectively; Slurm job elapsed times were 12:02 for A and 3:42 for B. Cached tokens are included in the input count. Token usage was local; no paid API was used.

## Interpretation

The verifier completed for both conditions, so these are task results rather than verifier-infrastructure failures. A made real but incomplete implementation progress: 18 of 70 functional checks passed, while all seven preference checks passed. Its agent did not finish; the Singularity HTTP request ended after 600 seconds despite Harbor reporting a 5,400-second agent limit.

B stopped before editing and produced no patch. Its lower functional score is therefore not evidence that memory harmed implementation, and this pair does not establish a memory benefit. The stop reason is directly recorded in the watcher artifact. The frozen memory contains general workflow/schema-integration advice but no rule for this task's partial-field semantics.

An earlier submission attempt failed before model execution because compute nodes lacked host `rg` (exit 127). The static ripgrep 15.2.0 binary is now available as `bin/rg`; both reported runs passed that preflight. The queue's RTX 3090 partition was available again on the day of these runs, so no hardware or model substitution was made.
