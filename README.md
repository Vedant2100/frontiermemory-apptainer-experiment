# Does agent-written memory actually help? A FrontierMemory study on local hardware

[FrontierMemory](https://frontiermemory.com/) asks whether a coding agent does better on new tasks when it can read a "memory" distilled from hundreds of earlier agent runs. The official leaderboard compares memory systems, but it never reports how agents do *without* memory. This repo measures exactly that: the same agent on the same tasks, with and without memory, using only free, local models on a university Slurm cluster.

## In one paragraph

We run the official FrontierMemory v1.0 tasks with Codex CLI driving a local Qwen3.8-27B model, inside Apptainer containers instead of Docker. Memory goes in through Codex's own memory mechanism, built from the official corpus with the official instruction. Every task is checked first: the reference solution must pass our grading setup before we trust any score. Early runs gave one striking result, on a Word2Vec task: 0/3 trials passed without memory and 3/3 with it. A second task (DAPT) showed a gain that did not hold up when we re-ran it. We also found that a local model cannot reliably tell whether a memory "lesson" is correct: two LLM judges and a rule-based checker all failed validation, and about half the lessons that cite evidence are not supported by the steps they cite. We then preregistered a larger experiment: 7 tasks, 3 memory conditions, 5 trials each. Two tasks are done so far, and Word2Vec replicated cleanly (no memory 0/5, both memory versions 5/5). The remaining five are running now. The results go into a short paper (target: FORGE 2027, Nov 15), followed by a memory-system submission to the leaderboard.

## What we compare

| Condition | What the agent gets |
|---|---|
| **A0** | No memory |
| **R25** | Memory built from a random 25% of the corpus (smaller) |
| **M3** | Memory built from the whole corpus, with a complete topic index |

Everything else is identical across conditions: task, model, prompt, time limit and grader. A plan fixed in advance ([preregistration](results/preregistration-v1.md)) sets the trial order and the analysis before any result is seen.

## Results so far

| Task | No memory | R25 | M3 |
|---|---|---|---|
| Word2Vec pipeline | 0/5 pass | **5/5** | **5/5** |
| DAPT intrusion detection | 0/5 pass (26.4/37 tests) | 1/5 pass (31.4/37) | 0/5 pass (20.0/37) |
| awilix (×2), customer-delivery, cattrs, cookie-store | running | | |

Things we learned along the way:

- **Memory helps most when a task depends on conventions from earlier runs.** On Word2Vec, every no-memory run failed to produce output in the required format; every run with memory got it right.
- **Codex only puts part of the memory into the prompt**: the first and last 5,000 characters. The rest is reachable only if the agent searches for it. Agents do search when the task cues them (all 10 Word2Vec memory runs did) and often skip it otherwise. We had predicted the opposite for M3 and were wrong; the [interim results](results/matrix-v1-interim.md) report that openly.
- **More memory isn't automatically better.** On DAPT, the smaller R25 memory did best and the full-corpus M3 did worst.
- **Checking memory quality automatically is hard.** Our attempts at a "memory governor" that filters bad lessons failed their own validation tests, so we report that as a finding ([governor summary](results/governor-validation-summary.md)).

## Still to do

- Finish the remaining five tasks (about 3 more days of GPU time, one job at a time).
- Final analysis.
- Memory-quality audit.
- A check of whether harm from memory comes from lessons about *other* tasks ("scope leakage").
- An audit of the corpus update: FrontierMemory released corpus v1.1 on Oct 29 to remove metadata that could enable reward hacking. Our study stays on v1.0, and we will check whether our memories contained any of that metadata.
- Write the paper.
- Package the memory builder as a leaderboard submission.

## How it's set up, briefly

- **Hardware and models.** Slurm cluster with RTX 3090 GPUs. Ollama serves Qwen3.8-27B. No paid APIs.
- **Containers.** Apptainer, since Docker isn't available, driven by Harbor's Singularity backend.
- **Deviations from the official setup.** Every one is listed in [the protocol](results/protocol-v3-official-like.md), for example network-mode staging and a uid workaround in some verifier images.
- **Grading checks.** Each task's grading path is checked with the reference solution ("oracle checks" in `results/*-oracle-check-summary.md`).
- **Decision history.** Every decision is in an append-only [decisions log](results/decisions-log-detailed.md). The earliest exploratory runs (Mini-SWE-Agent and OpenCode with smaller models, all scoring 0) are in [early exploration](results/early-exploration.md) and [history](results/history.md).

The gated corpus, task and verifier files, generated memories, raw agent traces and model weights are deliberately **not** in this repo. They stay on the cluster under the benchmark's access terms. The repo holds only code, methods and summarized results.
