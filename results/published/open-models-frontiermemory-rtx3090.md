# Open models for FrontierMemory on the Slurm RTX 3090

**Assessment date:** 2026-10-27  
**Scope:** Open-weight models relevant to local FrontierMemory task solving, using the cluster's 24 GB RTX 3090 jobs and existing shared Ollama store. This is a feasibility and evidence report, not a new benchmark run.

GPU feasibility below is grounded in completed Slurm runs and the repository's `vcggpu`/`rtx3090` job configuration. The current shell is a login node without `nvidia-smi`; current free GPU slots were not confirmed in this read-only pass.

## Main finding

There is no official FrontierMemory ranking of open task models to reproduce. The benchmark README says its published task-agent evaluation is constrained to Opus 5.5 and GPT-6 Sol. Its headline numbers compare memory systems while using those task agents. On the Word2Vec task page, the 100% results likewise use GPT-6 Sol as the task model; listed source trajectories, including one labeled Qwen3.7, are historical failures and are not a controlled model comparison. Therefore no open model can honestly be called the strongest *inside the official FrontierMemory evaluation* from the public results.

For our local exploratory work, the best-supported choice is **the cached Qwen3-Coder 30B Q4**. It is the only option here with both verified 32K-context service on a Slurm RTX 3090 and measurable partial progress on an official task: the no-memory cattrs run passed 18/70 functional checks and produced a nonempty patch. It did not finish or pass the original verifier overall. This is evidence for the current setup, not proof that the model is intrinsically better than alternatives.

## Candidates already in the shared model store

| Model | Local weight footprint | RTX 3090 / Slurm status | FrontierMemory evidence and recommendation |
|---|---:|---|---|
| **Qwen3-Coder 30B-A3B Q4_K_M** (`qwen3-coder:30b`) | 18.56 GB model layer | **Verified.** Previously served on an allocated RTX 3090 at 32K context. | Best immediate baseline: it produced 18/70 functional checks on cattrs. The paired memory run made no edits, so this does not show a memory effect. Reuse it for the next controlled task run. Apache-2.0; 30B total / 3.3B active. |
| **Qwen3.8 27B MTP Q4_K_M** (`qwen3.8:27b-mtp-q4_K_M`) | 17.74 GB including projector | **Verified.** Two no-memory cattrs attempts ran on an allocated RTX 3090 at 32K context; one reported about 17.45 GB VRAM for the loaded model. | Qwen reports 61.7% SWE-bench Pro and 73.0% Terminal-Bench 2.1. These are vendor-reported results under conditions different from FrontierMemory and from Devstral's benchmarks. In our two cattrs attempts it made no edits and scored 0/70 functional checks. Do not repeat with the same OpenCode configuration as the first choice. Apache-2.0. |
| **Qwen2.5-Coder 14B Q4_K_M** (`qwen2.5-coder:14b`) | 8.99 GB model layer | **Likely comfortable** on the 24 GB card; no current FrontierMemory task run located. | A lower-memory fallback if larger models fail to load or leave too little context headroom. It is older and has no demonstrated advantage on our tasks. Apache-2.0; Ollama lists 32K context. |
| **Qwen2.5-Coder 32B Q4_K_M** (`qwen2.5-coder:32b`) | 19.85 GB model layer | **Tight/uncertain** on a 24 GB card once runtime and KV cache are included; no successful local task run located. | Not recommended ahead of the tested 30B MoE model. A short-context or partial CPU-offload run may be possible, but would need a Slurm allocation check and would change serving conditions. |
| **Qwen2.5-Coder 7B Q4** (`qwen2.5-coder:7b`) | 4.68 GB model layer | Fits comfortably. | Prior Mini-SWE-Agent runs on Awilix failed to solve the task; use only as a cheap toolchain canary, not as the strongest worker. |

The sizes above come from manifests in `/home/csgrad/vbork001/shared-mem-gov-pilot/models`; they are decimal GB for model layers and exclude minor Ollama metadata unless stated. These weights are already cached, so these options require no new model download.

## Strong open candidate that is not ready to use

**Devstral Small 2 24B Q4** is attractive on paper: Mistral's model card reports 68.0% SWE-bench Verified and 55.7% SWE-bench Multilingual, and identifies the weights as Apache-2.0. Ollama lists a roughly 15 GB package. These are not FrontierMemory scores and should not be compared numerically with Qwen3.8's SWE-bench Pro or Terminal-Bench results.

The shared store contains only a **partial** Devstral download: its blob is about 15.18 GB logically, with about 7.53 GB currently allocated, and there is no completed Ollama manifest. It is not runnable from this cache as-is. A Q4 build may fit on a 24 GB RTX 3090 at a restrained context, but that has not been verified on our Slurm nodes. Given the current storage concern, the report does not recommend resuming the download now. Nothing was deleted or changed.

## Not feasible for this allocation

Qwen3-Coder-Next Q4 is listed by Ollama at about 52 GB before runtime memory. It is not cached and is not a practical single-RTX-3090 choice. It would add substantial storage and still exceed GPU memory without heavy offload or multiple GPUs.

## Recommendation

1. **Use cached Qwen3-Coder 30B Q4 for the next controlled FrontierMemory task.** Keep the current 32K context and Slurm RTX 3090 setup; it is the only model with demonstrated functional progress in our pipeline.
2. **Keep Qwen3.8 Q4 as a secondary candidate**, not the default: it runs on the hardware and has stronger-looking vendor-reported general coding scores, but the two local cattrs attempts stopped without edits.
3. **Consider Devstral Small 2 only if storage is confirmed and a GPU job can check fit first.** Do not resume its partial pull just to settle a speculative ranking.

The next experiment should select a task whose relevant historical evidence is verified, then hold task, harness, prompt, context, stopping rules, and verifier fixed. This report does not establish causal model differences or memory effectiveness.

## Sources

- [FrontierMemory benchmark README](https://github.com/letta-ai/frontiermemory): task-agent model constraint, benchmark design, and distinction between memory and task models.
- [FrontierMemory Word2Vec task page](https://www.frontiermemory.com/tasks/build-word2vec-pipeline/): published task results and historical source trajectories.
- [Qwen3-Coder 30B-A3B model card](https://huggingface.co/Qwen/Qwen3-Coder-30B-A3B-Instruct) and [Ollama model page](https://ollama.com/library/qwen3-coder): license, model description, and Ollama packaging.
- [Qwen3.8-27B model card](https://huggingface.co/Qwen/Qwen3.8-27B) and [Ollama tags](https://ollama.com/library/qwen3.8/tags): vendor-reported coding results, license, package size, and advertised context.
- [Qwen2.5-Coder Ollama tags](https://ollama.com/library/qwen2.5-coder/tags): package sizes and advertised context lengths.
- [Devstral Small 2 model card](https://huggingface.co/mistralai/Devstral-Small-2-24B-Instruct-2512) and [Ollama page](https://ollama.com/library/devstral-small-2): license, vendor-reported coding results, and package size.
- Local sanitized run records: [`cattrs-opencode-paired-3090-2026-10-26.md`](../cattrs-opencode-paired-3090-2026-10-26.md) and [`qwen38-cattrs-q4-baselines-2026-10-26.md`](../qwen38-cattrs-q4-baselines-2026-10-26.md).

No gated corpus contents, raw trajectories, task files, generated memory, or model weights are included here.
