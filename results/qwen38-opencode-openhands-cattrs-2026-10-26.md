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
This is a genuine no-progress task outcome, not a verifier or patch-collection
failure.

## OpenHands SDK attempt

Harbor 0.24.0 exposes an `openhands-sdk` adapter that runs the SDK in the task
container; it does not require Docker. The attempt used the same fresh staged
task, local Ollama model, RTX 3090 class, 32K Ollama context, shared no-memory
prompt file, `reasoning_effort=none`, temperature 1.0, and an eight-iteration
cap. The local Ollama API probe succeeded and showed the model loaded at 32K.

The adapter stopped during setup, before its first model call. Its pinned Harbor
implementation attempts to download `uv`, Python 3.12, `openhands-sdk`, and
`openhands-tools` inside the task environment. The first command,
`curl -LsSf https://astral.sh/uv/install.sh`, failed with exit 6:
`Could not resolve host: astral.sh`. Harbor classified this as
`NetworkConnectionError`; no trajectory, patch, tokens, or verifier result
exists for OpenHands. The adapter's installation path is visible in the
[Harbor OpenHands SDK source](https://github.com/harbor-framework/harbor/blob/v0.24.0/src/harbor/agents/installed/openhands_sdk.py).
No image rebuild or dependency-download workaround was attempted.

## Assessment

- **Tool-call compatibility:** Not the main observed OpenCode failure. The
  canary passed, and the cattrs calls were valid native calls with no literal
  tool markup. Patch collection and the original verifier worked.
- **Thinking/output use:** A real contributor to the earlier A2 failure. The
  default medium mode used the entire 8,192-token turn for reasoning. The
  corrected OpenCode config produced no reasoning blocks in the canary or
  cattrs trajectory.
- **Task progress:** Still failing under OpenCode after that correction. The
  cattrs attempt stopped after eight inspection-only turns with no edit/test.
  The evidence supports a model-plus-agent task-planning problem, but does not
  isolate model reasoning from OpenCode prompt/orchestration behavior.
- **OpenHands comparison:** Not measured. The adapter is blocked by compute
  container DNS during its dependency installation, before agent execution.
  Therefore there is no valid OpenHands-versus-OpenCode coding comparison.
- **Pi follow-up:** Also blocked before agent execution by DNS resolution for
  its NVM installer. Together these failures show that on-demand harness setup
  is constrained by container network access; they say nothing about either
  agent's coding quality.

## Recommendation

For future diagnostics, use the corrected OpenCode config, local Ollama
`reasoning_effort=none`, 32K context, the existing Q4 model, the working
collector/verifier path, and the 8-turn no-progress stop. This is the best
verified local execution configuration, but the cattrs result is not a
successful coding baseline. Do not start another memory A/B on this task until
an agent makes a real edit and runs a focused test. An OpenHands comparison
requires a preinstalled SDK/runtime in the existing image or an allowed offline
wheel/Python source; this attempt did not test OpenHands agent quality.

## Pi adapter canary follow-up

A bounded Pi 0.85.1 canary was submitted as Slurm job 300675 on the same RTX
3090, using the existing Qwen3.8 Q4 model, Ollama SIF, and Apptainer task
image. Ollama confirmed the model loaded with a 32,768-token context and
17,445,871,942 bytes in VRAM. The run used `openai-completions`, thinking off,
an eight-turn cap, and an empty-memory prompt wrapper.

Harbor's Pi adapter failed during setup before invoking the model. Its pinned
installer attempted to fetch NVM from `raw.githubusercontent.com`, which failed
with `Could not resolve host: raw.githubusercontent.com`; Harbor classified it
as `NetworkConnectionError`. The trial lasted about 23 seconds. There were no
model tokens, code edits, tests, nonempty patch, or verifier score. The canary
gate therefore failed, and no cattrs Pi run was launched. Harbor's failure
cleanup created a zero-byte `model.patch`; the verifier did not run. This is an
infrastructure failure, not evidence about Pi's coding ability. No workaround,
runtime install, or image rebuild was attempted.

## Local raw artifacts

Raw trajectories, prompts, patches, Ollama logs, task copies, and verifier logs
remain under ignored `jobs/`, `results/opencode-frontiermemory-tasks/`,
`results/openhands-sdk-frontiermemory/`, and `results/pi-frontiermemory-no-memory/`
paths. They are not included in the repository commit.
