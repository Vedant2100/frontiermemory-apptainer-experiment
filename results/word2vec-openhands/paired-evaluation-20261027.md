# FrontierMemory Word2Vec exploratory pair

**Status:** Both conditions ran to the OpenHands 30-iteration limit and produced code, but neither produced the task's required output artifact. The verifier collected zero tests. Harbor's reward of `0` is not a functional score, and this pair does not establish a memory benefit or harm.

## Matched setup

- Official task: `letta-ai/build-word2vec-pipeline`; task and verifier sources were left unchanged.
- Model: cached `qwen3.8:27b-mtp-q4_K_M` through local Ollama 0.40.11.
- Agent: OpenHands SDK 1.58.2, Harbor 0.24.0, Apptainer 1.5.2.
- Hardware: two RTX 3090 GPUs (24 GB each), Slurm partition `vcggpu`; model resident across both.
- Effective Ollama context: 65,536 tokens in both runs. The loaded-model API and request audit confirmed the value; no overflow occurred.
- Decoding: temperature 0.1, `reasoning_effort=medium`; the configured setting was present in the agent requests.
- Both used one fresh task workspace, the same base prompt template, and a 30-iteration limit. B appended only the frozen memory to that template.
- No weights were downloaded and no paid API was used.

## Results

| Measure | A: no memory | B: historical memory |
|---|---:|---:|
| Agent execution | 548.5 s | 472.4 s |
| Full Harbor trial | 589.4 s | 511.5 s |
| Input tokens (including cached) | 744,163 | 740,386 |
| Cached input tokens | 702,640 | 702,907 |
| Output tokens | 24,620 | 16,220 |
| Agent limit | 30 iterations reached | 30 iterations reached |
| Harbor reward | 0.0 | 0.0 |
| Original verifier cases collected | 0 | 0 |
| Required artifact collected | No | No |

A wrote `word2vec_model.py` and generated model/config/vocabulary artifacts. Its inline self-test eventually printed `OK`. B wrote `word2vec_component.py` and a saved model; its inline smoke checks eventually passed. B also tried to create a permanent test suite after reading the memory's testing advice, but the destination directory was absent, so that file write failed. Neither condition produced the task's declared `/workspace/solution.py`; Harbor therefore had no required solution file to collect, and the original verifier collected zero test cases. The verifier image started, but the evaluation handoff failed before functional scoring.

As a separate, nonstandard diagnostic, A's saved source was copied unchanged to a replay workspace under the declared filename and run against the same original verifier image. Collection still stopped because the implementation did not meet the task's callable contract. This replay is not counted as A's benchmark score. B's original verifier run stopped at the missing artifact path; its source and workspace are preserved locally.

## Memory provenance and observed behavior

The memory was generated locally by the same Qwen3.8 model from a 5,094-byte evidence pack selected from the pinned official `joint-674-v1.0` corpus. The generation input audit excluded this task, verifier, patches, and prior experiment notes. Generation took 80.4 seconds (1,428 prompt tokens, 1,361 output tokens) and produced 2,211 bytes. All eight citations were checked against checksum-verified source trajectories whose recorded final status was PASS.

The frozen memory contains schema/API integration and test-workflow lessons, not Word2Vec, NLP, or Gensim knowledge. Its relevance is weak and indirect. B spent 13 initial actions searching the empty workspace, installed packages, and run environment before editing; A also spent substantial early effort inspecting packages. B's later test-suite attempt is an observable response to the memory, but with no verifier tests collected and no task success, this single pair cannot support a causal claim about memory effectiveness.

## Interpretation and limits

The agent and verifier containers started, but the evaluation runner had a preventable configuration defect: although preflight recorded the task's declared artifact path, the shared A/B prompt wrapper did not tell the agent to create it. The agent also did not independently infer the required path. The separate replay indicates that simply renaming A's output would not have made it pass; its implementation still failed collection. The original verifier files were embedded unchanged. Since neither run reached functional cases, the lower B runtime and output-token count are not evidence of improved efficiency. The memory was only indirectly relevant. No leaderboard claim is made.

## Follow-up runner repair

After these runs, the shared runner was changed to build the prompt header from the staged task metadata's `declared_artifacts` list. Both conditions receive the same exact-path instruction before the task prompt; B still differs only by the appended frozen memory. The runner now refuses to launch if the metadata is absent, empty, or contains paths outside `/workspace/`. This repairs the missing artifact-path handoff for future runs; it does not change or retroactively validate A or B, and it does not resolve the implementation's callable-contract failure found in the diagnostic replay.

A follow-up no-memory run (`301863`) exercised the repaired path. Preflight passed, the generated prompt named `/workspace/solution.py`, Ollama reported a 65,536-token context, and the original verifier image/test hashes passed. OpenHands then spent 3:17 across six model requests inspecting the empty workspace, installed NLTK data, home/config locations, and the filesystem; it made no source edits and ran no task tests. Partial OpenHands telemetry at stop was 36,950 input and 3,810 output tokens. The Slurm job was cancelled under the early-stop rule and released its allocation. No verifier was run, so this is an agent-execution failure, not a benchmark result.

Raw trajectories, model requests, generated memory, corpus evidence, verifier logs, and implementation workspaces remain local. This report is the sanitized result record.
