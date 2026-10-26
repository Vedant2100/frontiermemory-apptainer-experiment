# Qwen3.8 no-memory baseline and Harbor adapter check

Exploratory diagnostic only. No memory condition or leaderboard claim. The
official `cattrs-compositional-changelog` task and verifier were not modified.

## Setup

- Task: FrontierMemory v1.0 `cattrs-compositional-changelog`, staged from the
  existing pinned task copy. Harbor created a fresh task state for the
  corrected OpenCode run and a separate fresh state for the OpenHands attempt.
- Model: existing local `qwen3.8:27b-mtp-q4_K_M` (Q4_K_M); no model download.
- Hardware: one RTX 3090 on `nodevcggpu01` for each run. Ollama reported
  `context_length=32768` and `size_vram=17445871942` bytes in both jobs.
- Reused versions: Harbor 0.24.0, OpenCode 1.19.4, Ollama 0.40.11, Apptainer
  1.5.2, existing SIFs and OpenCode runtime.
- No paid APIs or historical memory were used.

## What the saved Qwen3.8/OpenCode traces show

| Run | Agent/tool behavior | Output and stop | Task result |
| --- | --- | --- | --- |
| Earlier A1 | 35 assistant turns, 37 native calls (25 `read`, 5 `bash`, 3 `grep`, 3 task-tracker, 1 `write`); repeated repository inspection and summary turns; no source patch or test | 18,313 output tokens; operator stopped after 585.5 seconds of agent time | Empty patch; original verifier 0/70 functional, 7/7 preference, reward 0 |
| Earlier A2 | 6 assistant turns, 5 native calls (3 `read`, 2 `bash`); no source patch or test | Final turn ended with `finish_reason=length` at OpenCode's configured 8,192-token output limit. Its message was empty and its trajectory carried 34,879 characters in `reasoning_content`. OpenCode reported `reasoning=0`, so an exact thinking-token count cannot be recovered. | Empty patch; original verifier 0/70 functional, 7/7 preference, reward 0 |

Neither earlier trace contains literal `<tool_call>` or `<function=...>` markup
in assistant responses. The calls that did occur were native OpenCode tool
calls. The A1 trajectory includes repeated self-summary responses, then more
inspection. This points to an inspection/compaction loop, not malformed tool
call syntax. OpenCode's `--thinking` flag only includes thinking blocks in its
JSON output; it is not a request to disable model thinking.

Both earlier runs requested 32,768 context tokens. Ollama confirmed that exact
loaded context. In the long A1 trace, successive prompts reached roughly 25K
tokens before OpenCode compacted the conversation; there was no Ollama context
overflow error. The configured OpenCode output ceiling was 8,192 tokens, and
A2 demonstrably reached it.

## Thinking-control probe and corrected OpenCode config

Ollama `/api/show` reported the model's supported controls as `false`, `low`,
`medium`, and `xhigh`, with `medium` as the default. A small direct probe
returned 61 completion tokens and 121 thinking characters with the default;
native `think:false` returned 4 completion tokens and no thinking field; the
OpenAI-compatible `reasoning_effort:"none"` request also returned 4 completion
tokens and no reasoning field. These are control probes, not coding results.
Ollama documents the native `think` field and OpenAI-compatible reasoning
controls in its [thinking API documentation](https://docs.ollama.com/capabilities/thinking)
and [OpenAI compatibility documentation](https://docs.ollama.com/api/openai-compatibility).

The previous OpenCode custom provider was named `Ollama` while its provider ID
was `ollama`. The corrected config removes that mismatched name and selects a
`no-thinking` variant with `reasoningEffort:"none"`, while preserving the
model, 32K context, 8,192 output ceiling, permissions, and OpenCode 1.19.4.
The OpenCode source also confirms `--thinking` is a logging/display flag in
Harbor's [pinned adapter](https://github.com/harbor-framework/harbor/blob/v0.24.0/src/harbor/agents/installed/opencode.py).
OpenCode has documented option-forwarding behavior tied to custom provider
names in [issue #27361](https://github.com/anomalyco/opencode/issues/27361).

### Canary

| Agent | Edits/tests | Patch collector and separate verifier | Agent tokens |
| --- | --- | --- | ---: |
| OpenCode 1.19.4, corrected config | Created two files; all 4 focused `unittest` tests passed | 1,066-byte uncommitted patch collected; separate verifier passed (reward 1.0) | 34,608 input / 27,822 cached / 519 output; 22s agent execution, 69s total Harbor trial |

The canary trajectory had no reasoning blocks. This verifies that the corrected
configuration can perform native tool calls, write files, run tests, and pass
the separate Apptainer verifier through the existing Harbor collector.

### Fresh cattrs no-memory attempt

| Agent | Edits/tests | Stop and time | Original verifier |
| --- | --- | --- | --- |
| OpenCode 1.19.4, corrected config | 11 native tool calls over 8 assistant turns; no code edit, no test, empty patch | The shared early-stop guard interrupted after 8 consecutive assistant turns without an edit or test. Agent time 82.5s; total trial time 127.6s. Harbor records the resulting agent exit as code 130. | Verifier ran unchanged: functional 0/70, preference 7/7, reward 0 |

Harbor recorded 77,389 input, 37,999 cached, and 1,645 output tokens. The
trajectory had no reasoning blocks and the 8,192 output ceiling was not hit.
The unchanged verifier and patch collector worked, but this was stopped by a
no-progress guard after eight assistant turns, so it is a guard-censored
no-progress observation rather than evidence that the model could never solve
the task.

### Trace diagnosis: compaction loses task state

The corrected OpenCode trace exposes a concrete failure mode. After reading the
large `converters.py` file, the next request reached 27,417 prompt tokens. The
OpenCode log then records `agent=compaction mode=primary`. The compaction summary
incorrectly says no branch has been created, even though the immediately prior
tool output confirms `git checkout -b partial-structure` succeeded. It then
directs the agent to reread the full converter file. The next actions resume
repository inspection and the shared eight-turn guard stops the attempt before
an edit or test. Earlier A1 shows the same read/compaction/inspection cycle
repeated over many turns.

This is a model-and-context-management interaction, not an Ollama context
overflow or failed tool call: the loaded context was 32,768, and the tool
outputs show successful reads and branch creation. Large whole-file reads
triggered compaction; the generated summary then discarded true execution state
and encouraged rereading. The eight-turn stop policy further prevents these
runs from testing whether implementation would eventually begin.

## OpenHands SDK attempt

Harbor 0.24.0's `openhands-sdk` adapter runs the SDK inside the task container
and does not require Docker. The first attempt (job 300637) failed before its
first model call because the adapter tried to fetch `uv` from `astral.sh` and
task-container DNS could not resolve it. I resolved that without rebuilding the
image: the existing cluster UV/Python 3.12 runtime installed the adapter's
dependencies into a persistent local venv, and the repo's Singularity wrapper
binds it read-only at Harbor's expected `/opt/openhands-sdk-venv` path. The
staged versions were Python 3.12.15, UV 0.12.22, `openhands-sdk` 1.58.2,
`openhands-tools` 1.58.2, and FastAPI 0.162.0 (187 packages total). An
Apptainer preflight imported the SDK and tools from inside the existing task
SIF. The pinned package list and staging command are saved in
[`configs/openhands-sdk-python312-lock.txt`](../configs/openhands-sdk-python312-lock.txt)
and [`scripts/stage_openhands_sdk_runtime.sh`](../scripts/stage_openhands_sdk_runtime.sh).
No model was downloaded and no SIF was rebuilt.

One retry (job 300827) failed in my preflight because I invoked raw `apptainer`
and bypassed the bind-aware `singularity` wrapper. It ended before Ollama or
Harbor agent execution and is excluded from agent results. After correcting
that one command, job 300829 ran OpenHands on a fresh copy of the official
`cattrs-compositional-changelog` task, with the same RTX 3090, Qwen3.8 Q4 model,
32K loaded context, empty-memory prompt file, temperature 1.0,
`reasoning_effort=none`, and eight-iteration cap as the prior comparison. The
OpenHands task prompt intentionally reused the saved OpenCode prompt verbatim;
it includes OpenCode-specific tool wording, so tool/harness differences remain
a confound even though the task text and settings were held fixed.

| OpenHands no-memory run | Result |
| --- | --- |
| Agent behavior | Reached the eight-iteration cap in 43.3s (12 trajectory records); 10 valid native calls (5 terminal, 5 file views), all source inspection/search or a pytest-version/import probe; no source edit and no task test suite run |
| Patch | Empty (0 bytes) |
| Original verifier | Ran unchanged: functional 0/70, preference 7/7, reward 0 |
| Usage and time | 126,622 prompt tokens (103,305 cached), 721 output tokens; 43.3s agent, 99.3s total Harbor trial |

The SDK trajectory has no separate reasoning-token field; the run requested
`reasoning_effort=none`. The benchmark task's nine original verifier/test files
were byte-identical in the fresh task copy. Only that copy's `task.toml` has
the documented Apptainer/network/collector adaptations.

This establishes that the Harbor adapter, Apptainer bind, Ollama-compatible
endpoint, and OpenHands native tools execute together. The verifier ran and
returned a valid score for the empty patch, but the agent result is censored by
the eight-iteration limit; it is not evidence that a longer attempt would also
make no progress. LiteLLM's optional remote model-cost-map refresh logged DNS
warnings and used its bundled local fallback; model calls still succeeded at
zero cost. The earlier failed OpenHands job is setup-only and excluded.

## Assessment

- **Tool-call compatibility:** Not the main observed failure. OpenCode and Pi
  passed a small edit/test/collection/verifier canary. OpenHands passed its
  Apptainer/Ollama preflight and made 10 valid native calls on cattrs. No
  literal tool-call markup or adapter crash caused the no-progress outcomes.
- **Thinking/output use:** A real contributor to the earlier A2 failure. The
  default medium mode used the entire 8,192-token turn for reasoning. The
  corrected OpenCode config produced no reasoning blocks in the canary or
  cattrs trajectory. Pi was configured with thinking off, but its saved session
  contradicts treating that setting or `usage.reasoning=0` as proof: all seven
  completed assistant turns contain explicit `thinking` blocks (22,418
  characters total); one turn contains 21,088 such characters and reports
  4,986 output tokens. The client/server request path needs verification before
  claiming that Pi's reasoning was disabled. Its interrupted final generation
  has no final usage record.
- **Task progress:** Corrected OpenCode, Pi, and OpenHands all stopped before a
  cattrs source edit. OpenCode's no-progress guard and OpenHands' iteration cap
  both stopped at eight; Pi was manually stopped while its eighth response was
  still generating. These are censored attempts. The repeat-inspection pattern
  is consistent with weak task planning, compaction state loss, or a shared
  prompt/pacing problem, but does not isolate model capability.
- **OpenHands comparison:** Now measured as one no-memory run, not a causal
  harness comparison. Its SDK, native tools, and Ollama endpoint worked in
  Apptainer, but it also produced an empty patch and verifier 0/70. The reused
  prompt contains OpenCode-specific tool wording, and the harnesses have
  different iteration semantics.
- **Pi:** Its offline runtime bootstrap was repaired without rebuilding the
  Apptainer image. The Pi canary passed, but its real cattrs attempt produced
  no implementation progress and was stopped early. That is agent/task
  behavior, not an infrastructure failure. This was an exploratory harness
  comparison, not a fully matched causal experiment: harness system prompts,
  turn accounting, and stop events differ.

## Recommendation

For future memory experiments, OpenCode 1.19.4 remains the best operational
choice: its corrected no-thinking config and collector/verifier path are
simpler, and its edit/test canary passed. The cattrs runs do not establish a
reliable coding baseline: the model did not edit before an eight-turn stop, and
OpenCode compaction demonstrably lost branch state after a large file read.
Before another memory comparison, use a harness-neutral prompt, cap source reads
to relevant slices, require a concrete implementation plan/edit after at most
three inspection actions, and stop only for repeated identical actions or no
progress through the same overall budget. Retain raw responses so thinking
controls and compaction summaries can be checked. OpenHands' run is additionally
confounded by OpenCode-specific tool instructions. Pi's canary proves tool
execution, not benchmark-task coding ability.

## Pi offline bootstrap, canary, and cattrs attempt (2026-10-26)

The first Pi launch confirmed Harbor's default NVM bootstrap could not resolve
`raw.githubusercontent.com`. I fixed this offline rather than rebuilding the
task image: staged the pinned official `@earendil-works/pi-coding-agent@0.85.1`
and its npm dependencies beside the already-mounted Node 22 runtime, and
provided small `curl`/`npm` shims so Harbor's pinned installer sources the
staged Pi runtime instead of reaching the network. The NVM-generated PATH must
put the shim directory before the real npm binary; otherwise the networked npm
installer wins. The reproducible staging script is
[`scripts/stage_pi_offline_runtime.sh`](../scripts/stage_pi_offline_runtime.sh).
No container image was rebuilt and the official task/verifier were not
changed.

| Pi run | Work/result | Tokens and time |
| --- | --- | --- |
| Canary, job 300746 | Created two files, ran 4 focused `unittest` tests (4 passed), and Harbor collected a 1,082-byte uncommitted patch; separate canary verifier reward 1.0 | 6,804 input / 4,612 cached / 769 output tokens; 17.17s agent execution, 73.3s total trial |
| cattrs no-memory, job 300758 | Seven completed turns; 14 native calls (6 Bash, 8 read), all inspection/search; no source edit, test, patch, or verifier | 15,027 uncached input / 41,319 cached input / 5,949 completed output tokens. API total 62,295. Stopped after 7m51s job wall time (about 6m56s since Pi session start). |

Ollama confirmed the cattrs run used a 32,768-token loaded context and
17,445,871,942 bytes of model VRAM. At stop time the eighth response was still
generating at about 46 tokens/second; the last Ollama timing record showed
`n_gen=12226`. This server counter is not an API usage total and is not
interpreted as thinking tokens. The completed API records had zero reasoning
tokens. The process was manually stopped under the no-progress guard before
the configured eight-turn cap completed. There is no official cattrs verifier
score for Pi; this is an incomplete agent attempt, not a benchmark fail.

Harbor emitted a benign artifact-source overlap warning because `/logs/artifacts`
and `/logs/artifacts/model.patch` both map into its shared artifact directory.
It did not affect the canary patch collection. For cattrs there was no patch to
collect. Raw partial logs and the session trajectory remain local under the
ignored `results/pi-frontiermemory-no-memory/job-300758/harbor-partial/` path.

## Local raw artifacts

Raw trajectories, prompts, patches, Ollama logs, task copies, and verifier logs
remain under ignored `jobs/`, `results/opencode-frontiermemory-tasks/`,
`results/openhands-sdk-frontiermemory/`, and `results/pi-frontiermemory-no-memory/`
paths. They are not included in the repository commit. The local OpenHands
Python environment is under ignored `runtime/openhands-sdk-venv/`.
