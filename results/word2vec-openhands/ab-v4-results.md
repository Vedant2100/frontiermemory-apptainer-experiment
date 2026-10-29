# Word2Vec memory A/B with memory v4: official instruction (Slurm job 302175)

Date: 2026-10-28. Exploratory; n=3 per arm, one task, one local model. No leaderboard claim.

## Setup

Same runner and settings as jobs 301916, 302098 and 302125:
- Qwen3.8 27B Q4 on 2x RTX 3090, OpenHands SDK 1.58.2, Harbor 0.24.0 with the exec-timeout wrapper
- 65,536 context, temperature 0.1, reasoning medium, max_iterations 200, 1200 s timeout
- trial order A B B A A B; prompt template sha `cc02f24b…` identical in all 6 trials

Only the memory file differs.

Memory v4 (job 302127, frozen sha `b2566a31…`, 4,137 bytes):
- Generated locally from the same 14 word2vec-family trajectories as v3 (untruncated).
- Map and reduce prompts are the official `frontiermemory/src/frontier_memory/dream_task/instruction.md` verbatim (sha `a96e69af…`) plus one framing line each. No request for recipes or exact interfaces.
- The official instruction forbids copying final answers or prior final artifacts.

Lead audit of v4 (against the task instruction only):
- It misreads one PASS run (t0661) as FAIL.
- It warns against using the delivered entry-point interface, calling it a failure mode. PASS runs actually delivered that interface.
- It keeps correct preprocessing, `min_count=1`, and environment facts.
- 6 of 22 bullets cite evidence. Citations are informational; the official format does not require them.

## Per-trial results

| # | Arm | Outcome | Strict | Cases / 6 | Agent s | Requests | Input tok | Output tok |
|---|---|---|---|---|---|---|---|---|
| 1 | A | collection error: NLTK resource lookup at import | 0 | 0 | 446 | 35 | 580,960 | 14,300 |
| 2 | B | tests failed | 0 | 2 | 628 | 32 | 953,868 | 20,294 |
| 3 | B | tests failed | 0 | 5 | 115 | 8 | 88,623 | 3,828 |
| 4 | A | collection error: required callable missing | 0 | 0 | 199 | 14 | 172,871 | 6,736 |
| 5 | A | collection error: NLTK resource lookup at import | 0 | 0 | 416 | 26 | 511,534 | 12,573 |
| 6 | B | PASS | 1 | 6 | 415 | 23 | 426,590 | 13,656 |

All trials are valid, with no Harbor exception.

## Reading

- A: 0/3 strict, 0/3 collected. B: 1/3 strict, 3/3 collected, mean 4.3/6 cases.
- Despite advising against the delivered entry point, the memory names its exact signature. All three B artifacts met the callable contract.
- The wrong advice did not prevent use of the right interface. It is a qualitative warning about weak memory models under the official rules.

## Memory ablation ladder on Word2Vec (same harness and settings)

| Memory | Construction | Strict A (no memory) | Strict B | B collected | B mean cases / 6 |
|---|---|---|---|---|---|
| v2 | 14 family trajectories, per-step truncated, custom prompt | 0/3 | 0/3 | 3/3 | 1.0 |
| **v4** | 14 family trajectories, untruncated, **official instruction** | 0/3 | **1/3** | 3/3 | 4.3 |
| v3 | 14 family trajectories, untruncated, custom "reference recipe" (non-compliant) | 0/6 | 6/6 | 6/6 | 6.0 |

No-memory arms across all four jobs: 0/12 strict.

v5 (whole corpus, official instruction, one memory for all tasks) is the protocol-faithful rung and is in progress.
