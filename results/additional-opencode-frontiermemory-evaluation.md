# Additional FrontierMemory OpenCode task runs

Date: 2026-10-25
Starting revision: `ad3b68c35d6388013c578a23417208a3f2d559c5`

This is a small exploratory follow-up, not a leaderboard submission. It reuses the working local stack and the frozen memory artifact from the prior run.

## Setup and controls

- Harbor 0.24.0, its OpenCode adapter, OpenCode 1.19.4, Ollama 0.40.11, and the existing Apptainer task images.
- Local `qwen3-coder:30b` Q4 on an RTX 3090. Ollama polling recorded a loaded context of 32,768 tokens in every trial; the model used about 21.7 GB of VRAM.
- Official FrontierMemory v1.0 tasks: `cattrs-compositional-changelog` and `cookie-store-compositional-changelog`. Their benchmark instructions and verifier sources were not modified. Evaluation ran from fresh task copies.
- A has no memory. B uses the already frozen historical-corpus memory, SHA-256 `4ef8ff784aed9ce00d4532bedf3432347aa9af3185628252ec43c3ffa135bcd0`. No memory generation was run against either target task.
- For each A/B pair, the prompt templates are byte-identical after replacing the memory body with a common slot marker (SHA-256 `6a42b1dd81ac7565acdddb22f756be9744b0947c67adcebf44243d6415f8aefc`). The Harbor configurations are identical except for the template path. The model, agent, task, and stopping watcher were held fixed.
- The watcher stops a run on repeated tool errors or command/edit loops. It stopped cattrs B after the same search-tool error occurred three times in its recent call window.
- Harbor's Singularity backend cannot enforce the task's `no-network` setting. Both staged conditions therefore use Harbor's accepted `public` setting. This is a nonstandard limitation shared by A and B; network isolation is not claimed.

## Results

| Task / condition | Original verifier result | Functional / preference | Agent outcome | Steps; input / cached / output tokens | Agent / trial time |
|---|---|---|---|---|---|
| cattrs A, no memory (299276) | Fail, reward 0 | 0/70; 0/7 | Edited source and a local test, attempted focused and project tests, but did not commit. Harbor's configured collector only collected committed changes, so the verifier received an empty patch. | 68; 924,765 / 834,976 / 14,839 | 9m44s / 10m27s |
| cattrs B, frozen memory (299281) | Fail, reward 0 | 0/70; 0/7 | No source edit or test run. Stopped after three repeated search-tool errors (two `grep`, one `glob`); Harbor still ran the original verifier against the empty patch. | 9; 45,723 / 45,398 / 236 | 26s / 1m09s |
| cookie-store A, no memory (299296) | **Invalid: verifier infrastructure error** | Preference artifact: 0; functional score unavailable | Produced an 18,563-byte patch changing two source files and attempted pytest commands. The verifier reset reported an upstream test fixture missing and could not apply the official test patch; Harbor produced no reward result. | 35; 413,824 / 375,155 / 12,811 | 7m33s / 8m15s |
| cookie-store B, frozen memory (299297) | **Invalid: verifier infrastructure error** | Preference artifact: 0; functional score unavailable | Produced a 15,890-byte patch changing two source files. No pytest command was recorded. The same verifier failure prevented a reward result. | 22; 296,913 / 236,434 / 6,029 | 4m03s / 4m44s |

Times are agent execution and whole Harbor trial, respectively. “Input” is the model's reported prompt-token count; cached tokens are a subset of input. Token counts are local Ollama usage, with no paid API cost.

## Interpretation and verifier limitation

The initial cattrs pair is not a scorable coding comparison. A made implementation edits but did not commit them, so the configured patch collector passed no changes to the verifier. B stopped early after repeated tool errors and likewise supplied no patch. This is not evidence of a memory benefit.

Cookie-store A and B both made source edits, but neither has a valid functional score. The verifier SIF at SHA-256 `202c0993e79ad7d8228e35a01c850beee1c473d49e2638f0f7340148799d3407` passed an offline preflight: its `/app` Git HEAD was the pinned upstream base and its Git tree contained the fixture. The official test patch also applied cleanly to the matching upstream checkout. During both Harbor trials, however, the verifier reset reported that fixture absent from its runtime Git tree and then failed to apply the test patch. The inspected image and runtime verifier workspace therefore disagree. The cause of that discrepancy was not established; these cookie-store outputs must not be compared as verifier pass/fail results.

The cookie verifier image was rebuilt to include the upstream Git metadata and test tree after the first attempt revealed that copied but untracked fixtures were removed during verifier reset. That change still did not repair the runtime discrepancy, so no more container changes were made. The original benchmark verifier and task files remain unchanged.

## CPU-only repair and replay follow-up

The saved cookie-store A and B patches were replayed through the same pinned verifier image (`202c0993e79ad7d8228e35a01c850beee1c473d49e2638f0f7340148799d3407`) against the exact pinned upstream source. The benchmark task, original verifier scripts, and SIF were unchanged. The prior failure was a Git environment mismatch: `safe.directory=/app` was set only inside the verifier's patch-capture block, while Harbor's imported-verifier path skips that block and later runs reset/apply as `agent`. Git rejected the checkout as a dubious-ownership operation; the script suppressed that error and removed a tracked fixture. Supplying `GIT_CONFIG_COUNT=1`, `GIT_CONFIG_KEY_0=safe.directory`, and `GIT_CONFIG_VALUE_0=/app` to the verifier process fixed both replays without changing benchmark files.

| Replayed condition | Original verifier | Baseline suite | Task suite | Preference | Classification |
|---|---:|---:|---:|---:|---|
| Cookie-store A, no memory | Functional reward 0 | 1,284 passed, 4 skipped, 1 error | 89 passed, 26 failed | 0/1 | Candidate implementation failure after verifier setup completed |
| Cookie-store B, frozen memory | Functional reward 0 | Import-time collection failure | Import-time collection failure | 0/1 | Candidate patch failure after verifier setup completed |

The official test patch applied in both replays. A's code reached the task suite but did not satisfy it; B's candidate failed during module initialization before either test mode could collect. These are task failures, not the earlier fixture/infrastructure failure. The functional result is 0 in both conditions; this does not show a memory benefit. The preference artifacts also failed independently.

The cattrs task collector is exactly `git diff --binary <base> HEAD`, so an uncommitted working-tree edit is invisible to it. A CPU-only canary used a disposable copy of the pinned source and a README-only marker: the collector produced a 0-byte patch while the edit was uncommitted; after committing it, the same collector produced a 599-byte patch that applied cleanly. The unchanged cattrs verifier image then reported `model.patch applied (599 bytes)` and generated its normal reward report with reward 0, as expected for a README-only canary. This validates committed-edit-to-verifier handoff, not task implementation. No benchmark files were changed.

The cattrs B raw trace contains two `grep` calls (`class BaseConverter`, then `BaseConverter`) and one `glob` call (`**/*converter*.py`). All three returned `ripgrep execution failed`; OpenCode logged an attempt to download ripgrep 15.1.0. The watcher counts matching error strings across tool types, so it correctly stopped at three total failures and labeled the final call (`glob`) in its summary. This is a search-tool/environment failure, not evidence that memory harmed implementation.

The frozen memory checksum remains `4ef8ff784aed9ce00d4532bedf3432347aa9af3185628252ec43c3ffa135bcd0`, and it was not regenerated. Its 13 cited trajectory-step references resolve in the local `joint-674` snapshot (9 unique sources; all 9 have a final verifier-PASS marker). However, the curation note claims `joint-674-v1.0`: against that separately validated snapshot only 7 of 13 references resolve as cited (one referenced JSON file is absent as JSON and another is not step-based; the cited ranges also differ). Therefore exact v1.0 provenance is not established, and this memory should not be described as verified v1.0-derived until that mismatch is resolved. Based only on the public task descriptions and memory text, its advice has partial process-level relevance to both tasks (reproductions, edge cases, staged testing), but it contains no cookie-policy or partial-structuring guidance and no explicit documentation/changelog preference lesson. Target-specific relevance is low. No hidden verifier detail or task solution was used for this assessment.

These CPU-only replays and canaries do not change the earlier agent trajectories, steps, tokens, or timings. Patches, generated memory, corpus files, SIFs, and raw verifier logs remain local and ignored. No model was loaded and no GPU was used.

Raw trajectories, patches, verifier logs, task data, model files, and generated memory remain local and ignored. This published summary contains aggregate outcomes only. No leaderboard claim is made.
