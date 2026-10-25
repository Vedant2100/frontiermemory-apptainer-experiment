# OpenCode + Qwen3-Coder 30B: Awilix task attempt

Date: 2026-10-25. This is a diagnostic attempt, not a valid A/B result or a leaderboard submission.

## Outcome

Harbor 0.24.0 launched its built-in OpenCode 1.19.4 adapter on the official `awilix-release-tier-implicit` task, configured for the local Ollama Qwen3-Coder 30B Q4 model on an RTX 6000 Ada. OpenCode created a session and stored the user task, then exited with `UnknownError: Unexpected server error`. Ollama logged no inference request, its loaded-model endpoint remained empty, and the OpenCode session had no assistant response.

| Measure | A: no memory |
|---|---:|
| Slurm job | `299049`, completed, exit 0 |
| Configured model / harness | Qwen3-Coder 30B Q4 via Ollama 0.40.11 / OpenCode 1.19.4 |
| OpenCode invocations | 1 |
| Assistant/model turns | 0 |
| Shell/tool actions by agent | 0 |
| Source edits | 0 |
| Agent tests attempted | 0 |
| Input/output model tokens | 0 / 0 observed; Harbor usage fields were null |
| Agent execution | 1.46 s |
| Harbor trial, including setup and verifier | 52.66 s |
| Original verifier reward | 0.0 |
| Functional / release-preference rewards | 0 / 0 |
| Actual loaded context | Not verified; Ollama reported no loaded model |
| B condition | Skipped; no memory was generated |

The task and its original verifier were not modified. The verifier's functional suite could not compile the unchanged baseline because the requested API was absent, so zero functional tests ran. Its release-preference check also failed because the baseline did not contain the requested release-tier change. These are baseline verifier failures after an OpenCode infrastructure error; they do not measure whether the model could implement the feature or benefit from memory.

The collected patch contains only four `peer: true` package-lock metadata additions and no TypeScript or JavaScript source changes. OpenCode's database records one user message, no assistant message, and zero token counters. The task agent itself ran no tests or tools.

## Context and runtime

The Slurm job set `OLLAMA_CONTEXT_LENGTH=65536`, and the Harbor OpenCode model definition declared a 65,536-token context limit with 8,192 output tokens. However, `/api/ps` returned no loaded model at every poll and Ollama logged no chat/completion request. The configured context length therefore cannot be reported as an actual loaded context for this run.

Harbor's adapter, task copy, and original verifier were reused. Harbor's default OpenCode setup attempted to download NVM from `raw.githubusercontent.com`, which the task environment could not resolve. To avoid rebuilding the task SIF, the pinned smoke-test Node/OpenCode runtime was mounted through the existing `/staging/env_files` bind, with small `ldd` and npm shims so Harbor's own install command selected the offline runtime. That setup completed successfully. The later internal OpenCode error had no more specific cause in the captured logs; no inference request reached Ollama.

## Attempts

| Slurm job | Result |
|---|---|
| `299046` | Failed during Harbor's OpenCode installation when task-container DNS could not resolve `raw.githubusercontent.com`; no model request or verifier run. |
| `299047` | Failed before agent setup because Harbor was asked to reuse an existing job directory with a different config; no model request or verifier run. The next submission added the Slurm ID to each Harbor job name. |
| `299049` | Reached the task and original verifier, but OpenCode returned the internal server error described above. |

Condition B was intentionally skipped because A produced no substantive source edit. Historical-memory generation did not run, so the target task was not exposed to memory generation. No memory-versus-no-memory conclusion can be drawn from this attempt.

Raw Harbor logs, the task prompt, verifier output, OpenCode database, and patch remain in the local ignored run directories. This published report contains only sanitized aggregate results; gated corpus data and derivatives are excluded.
