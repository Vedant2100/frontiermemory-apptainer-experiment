# Word2Vec memory A/B with memory v3 (Slurm job 302098)

Date: 2026-10-28. Exploratory; n=3 per arm, one task, one local model. No leaderboard claim.

## Setup

Identical to job 301916 (`results/word2vec-openhands/ab-v2-results.md`) except the memory file.

| Item | Value |
|---|---|
| Task | `letta-ai/build-word2vec-pipeline`, original task and verifier, fresh staged copy per trial |
| Model / harness | `qwen3.8:27b-mtp-q4_K_M` (Ollama 0.40.11, 65,536 context, temperature 0.1, reasoning medium), OpenHands SDK 1.58.2, Harbor 0.24.0 + exec-timeout wrapper, Apptainer 1.5.2, 2x RTX 3090 |
| Limits / order | max_iterations 200, 1200 s agent timeout; A B B A A B in one job |
| Base prompt template | sha256 `cc02f24b…`, identical in all 6 trials |
| Memory (B only) | frozen v3, sha256 `fe61fdff…`, 3,518 bytes, job 302091 |

All data stayed on the cluster. No external model API was used.

## Memory v3

Memory v3 was generated locally by the same Qwen3.8 model from the same 14 word2vec-family corpus trajectories as v2 (3 PASS, 11 FAIL).
- Steps were not truncated. Only one long command output was capped at 4,000 chars.
- The map prompt asked for exact delivered interfaces, preprocessing order and parameters. The reduce prompt asked for a cited "reference recipe" from PASS runs.
- Output: 14 bullets, 39 citations, all resolved. The 5 recipe bullets cite PASS runs only.
- The lead spot-checked the cited PASS steps; they contain the recipe's interface, regex, stopwords source and parameters.
- The model never saw the target task, its verifier, its solution, or our notes.

## Per-trial results

| # | Arm | Outcome | Strict reward | Cases passed / 6 | Agent s | Requests | Input tok | Output tok |
|---|---|---|---|---|---|---|---|---|
| 1 | A | collection error: required callable missing | 0 | 0 | 126 | 8 | 81,457 | 5,493 |
| 2 | B | PASS | 1 | 6 | 123 | 11 | 132,491 | 5,696 |
| 3 | B | PASS | 1 | 6 | 62 | 5 | 49,403 | 2,479 |
| 4 | A | collection error: NLTK resource lookup at import | 0 | 0 | 78 | 7 | 65,278 | 2,839 |
| 5 | A | collection error: required callable missing | 0 | 0 | 816 | 43 | 1,226,233 | 35,897 |
| 6 | B | PASS | 1 | 6 | 96 | 11 | 130,425 | 4,234 |

Trial 4 is labeled `CONTRACT_COLLECTION_ERROR` by the record helper. The raw verifier output shows an NLTK `LookupError` at import, as reported above.

## Per-arm summary

| Arm | Strict passes | Mean cases / 6 | Mean agent s | Mean output tok |
|---|---|---|---|---|
| A (no memory) | 0/3 | 0.0 | 340 | 14,743 |
| B (memory v3) | **3/3** | **6.0** | 94 | 4,136 |

## Comparison with earlier runs on the same task

| Run | Memory | A strict | B strict | B cases / 6 |
|---|---|---|---|---|
| 301916, Qwen3.8 + OpenHands | v2 (truncated evidence) | 0/3 | 0/3 | 1 each |
| 302067, Codex `gpt-reserve` | v2 | 0/3 | 0/3 | 1 each |
| **302098, Qwen3.8 + OpenHands** | **v3 (untruncated evidence)** | **0/3** | **3/3** | **6 each** |

Across 9 no-memory trials on two stacks, none passed. With memory v3, all 3 trials passed, using fewer requests and tokens.

## Caveats

- n=3 per arm, one task, one model. The difference (3/3 vs 0/3) is large but the sample is small.
- This task asks for conventions and an interface "used by prior implementations". The memory supplies them from historical PASS runs of the same task family. That is what FrontierMemory is designed to measure. It does not show that memory helps on tasks that do not depend on prior runs.
- Evidence was family-selected (14 trajectories chosen by keyword), not produced by a whole-corpus memory run (deviation D2).
- Researcher degree of freedom: the v3 pipeline was designed after the v2 results. By then the lead knew from verifier errors which callable was required. The v3 prompts ask generically for interfaces and signatures and never name the callable. The memory model recovered it from the trajectories, and every recipe line cites PASS steps.
- Validity rule D5' and the Harbor Singularity exec-timeout wrapper apply as in job 301916. The verifier network mode is `public`; egress isolation is not enforced.
- Raw trajectories, generated code, memory text and verifier output stay local.
