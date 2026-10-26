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

## Latest CPU runner repair and v1.0 memory audit (2026-10-25)

The staged Apptainer task copy now uses `git add -A` followed by a binary diff against the official base commit. This captures committed, dirty tracked, and untracked agent edits. A disposable CPU canary produced an 825-byte patch containing an uncommitted `README.md` edit and an untracked file. The unchanged official verifier applied that patch and wrote its normal reward JSON. The official cattrs task TOML and verifier/test files remain unchanged; staged verifier/test files match the source byte-for-byte. This proves artifact handoff, not a valid task score.

The host's ripgrep 15.2.0 binary is bound read-only at `/usr/local/bin/rg` in both existing Apptainer SIFs. Search canaries succeeded in the agent and verifier images.

The cattrs verifier did not reach a valid test result. Pytest 9.0.3 rejected `/tmp/pytest-of-agent` because the process running as `agent` (UID 10001) did not own that directory. Apptainer reported that the account has no `/etc/subuid` entry and was using a root-mapped fakeroot namespace. Re-running with a fresh `TMPDIR` and pre-creating the pytest directory did not resolve the ownership check. The verifier emitted reward 0 after its tests failed during setup; that value is not a task score. No A/B agent run was launched with this verifier state.

The pinned `joint-674-v1.0` corpus manifest hash is `c7d31214ed20af4f14f46c4b9a838ebc9aa35a9491dfbce0fa50f7aa456eedd1`; all 674 listed file checksums were verified. Every cited step in historical trajectories `t0011.json` and `t0343.json` exists in those exact checksummed files, and both traces carry a final PASS marker. A CPU-curated 705-byte candidate memory has moderate process-level relevance to cattrs' public API feature: it advises mapping cross-cutting API integration paths and validating affected suites. It contains no cattrs-specific behavior. The candidate and evidence excerpts remain local. The local Qwen3-Coder 30B was not available for memory generation, so this candidate is not the model-generated frozen memory required for a paired run and was not used in evaluation.

At this check, no Slurm job was active, the current shell had no `nvidia-smi` or host Ollama endpoint, and no model was loaded. The A/B pair remains unrun. The remaining blockers are the cattrs verifier's Apptainer UID ownership failure and unavailable local-model generation for the corrected memory. No leaderboard claim is made.

## CPU runner repair, v1.0 memory generation, and cattrs runs (2026-10-26)

This section supersedes the 2026-10-25 checkpoint above. The original task files and verifier remain unchanged.

### Runner and verifier repair

- The staged Apptainer task collector uses `git add -A` before a binary diff from the pinned base commit. A CPU canary with an uncommitted edit and a new untracked file produced an 825-byte patch containing both. The earlier cattrs A run's collector had captured an empty patch; its saved successful edit/write calls were therefore replayed separately, as described below.
- The host ripgrep binary is bound read-only into the existing agent and verifier SIFs. A later OpenCode `glob` call succeeded offline.
- Pytest 9's temp-directory ownership error was fixed at runtime with a verifier-only `sitecustomize.py` bind that sets a task-owned `--basetemp` when the official verifier has set `PYTEST_ADDOPTS`. The original verifier script and SIF were not modified. A CPU canary ran the original verifier to completion: baseline suite 7/7 passed; the feature tests could not collect against the documentation-only canary, as expected; the verifier returned its normal reward artifact. This canary checks runner plumbing, not task functionality.

### Historical memory provenance

- The pinned `joint-674-v1.0` corpus manifest SHA-256 is `c7d31214ed20af4f14f46c4b9a838ebc9aa35a9491dfbce0fa50f7aa456eedd1`; all 674 manifest entries were checksummed. The local model generated a 1,514-byte memory from selected historical agent messages only (1,397 prompt tokens, 343 completion tokens, 18.3 seconds). The task prompt, task verifier, patch, and prior experiment notes were not supplied; the generation input and output contain no cattrs or target-task markers.
- Citation validation checked all eight memory references against the exact supplied excerpts, confirmed every cited step exists in the manifest-matching source files, and confirmed both sources ended with verifier PASS. The generated memory is frozen locally with checksum `0b97695a6643b962f66db830aa597c29551744a01896023581a0b9c1c6275797`. Corpus, excerpts, memory, citation records, and raw generation logs remain local.
- Relevance is moderate at the workflow level and low at the feature-semantics level. One lesson about aligning public APIs, implementation paths, and existing tests applies to this public API task. The memory does not teach partial-field recovery, recursive semantics, or refinement behavior. No task-specific rule was added after generation.

### Matched A/B run on an A5000

Both runs below used Harbor 0.24.0, OpenCode 1.19.4, Ollama 0.40.11, `qwen3-coder:30b`, Apptainer 1.5.2, the same cattrs task copy and 32,768-token context on the same RTX A5000. Ollama `/api/ps` verified the loaded context in each run. The rendered prompt wrappers and agent configs are identical after removing the memory slot; A left that slot empty and B inserted only the frozen memory. The same early-stop watcher was used.

| Condition | Agent behavior | Steps / tool calls | Agent tests | Prompt / cached / completion tokens | Agent / Harbor time | Original verifier |
|---|---|---:|---|---:|---:|---|
| A, no memory (job 300092) | Three repeated edit errors triggered the early stop; no source edit. | 29 / 27 | None | 400,264 / 331,278 / 4,242 | 157.3s / 201.8s | Reward 0; feature 0/69; baseline 7/7; preference 0/1 |
| B, historical memory (job 300095) | Three successful inspection/search calls, then the agent ended before editing; no watcher repetition stop. | 5 / 3 | None | 26,463 / 19,768 / 104 | 14.3s / 58.7s | Reward 0; feature 0/69; baseline 7/7; preference 0/1 |

The patch collector worked in both conditions; both emitted an empty patch. B had the full task instruction, the frozen memory, and a verified 32K context, but did not reach implementation. These matched runs do not show that memory helped or harmed coding; neither run made a source edit.

### Recovered earlier no-memory A

The earlier RTX 3090 A run (job 299276) had 68 trajectory steps, 62 tool calls, and real source and test edits, but its original Harbor collector emitted a zero-byte patch because the changes were not committed. The saved successful edit/write inputs were reconstructed against the pinned upstream checkout as a 10,468-byte patch and replayed through the unchanged original verifier. This is a transcript-recovered replay, not an artifact captured from the original working tree, and it used a 3090 rather than the A5000 used above.

The replay completed with reward 0: the baseline suite passed 7/7, the task feature suite passed 13/69 (56 failed), and the user-preference check was 0/1. The agent had reported its own tests as passing, but the original verifier did not support that claim. Its saved run used 924,765 prompt tokens (834,976 cached), 14,839 completion tokens, 9m43.8s agent time, and 10m26.8s Harbor time. The reconstructed patch attempted whole-object structuring and did not implement field-level partial results. Treat this as recovered evidence of implementation progress, not as the A side of the matched A5000 pair.

All raw trajectories, patches, verifier logs, benchmark files, corpus data, generated memory, and model files remain local and ignored. These are exploratory results; no leaderboard claim is made.
