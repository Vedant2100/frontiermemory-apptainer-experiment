# Qwen3.8-27B no-memory cattrs baselines (2026-10-26)

Exploratory diagnostic runs only. No memory condition or leaderboard claim.

## Setup

- Official FrontierMemory v1.0 task: `letta-ai/cattrs-compositional-changelog`; task checksum `45fda195e6d9582d36a1a3c7e07fb11a6a33b4932085cb9946415410afa05280`; upstream cattrs base commit `6bc4708fb9b2ac52d9a18997e923da6a58916102`.
- Model: `qwen3.8:27b-mtp-q4_K_M`, 27.3B parameters, Q4_K_M, 17,741,872,154 bytes; Ollama model digest `22130167c4c20e20c7b71454612966ca8e8171e9b3cc8ab6ce8aa6cbfec79643`. The [official Ollama tags page](https://ollama.com/library/qwen3.8/tags) lists this Q4 tag and the corresponding Q8 tag.
- The planned RTX 6000 Ada/Q8 allocation was unavailable: all three Ada nodes had all seven GPUs allocated. Following the 24 GB fallback, both attempts used one RTX 3090 on `nodevcggpu01`. This did not test Q8.
- Reused Harbor 0.24.0, OpenCode 1.19.4, Ollama 0.40.11, Apptainer 1.5.2, the existing SIFs, runtime, and benchmark staging. No paid API or new framework was used.
- OpenCode was configured for 32,768 context tokens and 8,192 output tokens. Ollama `/api/ps` recorded `context_length=32768` and `size_vram=17,445,871,942` bytes after loading the model.
- Both attempts used fresh task states, the same no-memory prompt wrapper (SHA-256 `b9d06bc0df68ab708caea06d89920bca4cf633eceef1ecc56fb1017900fb267c`), model, agent, task, verifier, and stopping watcher. The original task and verifier were unchanged.
- Nonstandard download workaround: the compute node could resolve `ollama.com` but its DNS resolver refused lookups for Ollama's Cloudflare R2 model blob host. After canceling the stalled pull job, I downloaded the public model from the login host into the same persistent shared Ollama store. Model inference and both evaluations ran on the allocated RTX 3090. Harbor's existing Apptainer task environment uses its accepted `public` network mode; shell egress was not isolated.

## Results

| Attempt | Agent outcome | Patch / tests | Original verifier | Steps / tool calls | Input / cached / output tokens | Agent / trial time |
| --- | --- | --- | --- | ---: | ---: | ---: |
| A1 | Manually stopped after 9m45s with read-only inspection and repeated compaction turns; no same-command loop triggered | 0 bytes; no source edit or test command | Reward 0; functional 0/70; preference 7/7 | 36 / 37 | 566,271 / 404,877 / 18,313 | 585.5s / 632.7s |
| A2 | OpenCode exited normally after a response reached the 8,192-token output limit (`finish_reason=length`) | 0 bytes; no source edit or test command | Reward 0; functional 0/70; preference 7/7 | 7 / 5 | 60,444 / 22,162 / 9,993 | 274.6s / 319.4s |

Both original verifier runs completed successfully against empty patches. Their partial score was `0.0909090909`, reflecting the 7/7 preference checks despite 0/70 functional checks. A1's agent was interrupted by the operator after 585 seconds; Harbor still collected an empty patch and ran the original verifier. A2 ended without a Harbor exception, but did no coding work before hitting its output limit.

## Interpretation

Neither attempt made implementation progress or ran tests. This Q4/RTX 3090 diagnostic did not improve on the prior Qwen3-Coder 30B partial result of 18/70. The two outcomes are evidence of poor execution with this model, quantization, prompt, and OpenCode setup on this task; they do not establish that Qwen3.8-27B Q8 on an Ada GPU would behave the same way. Since neither run made a code change, no historical-memory run was started and this experiment says nothing about memory effectiveness.

## Artifacts

The Slurm logs, both OpenCode trajectories, task copies, generated prompts, empty patches, and verifier output remain local and ignored. Only this aggregate report, the model-specific OpenCode config, and the reusable Slurm runner change are published.
