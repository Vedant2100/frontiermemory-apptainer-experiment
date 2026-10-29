# Main A/B: whole-corpus memory v5 vs no memory (Slurm jobs 303008, 303009)

Date: 2026-10-29. Exploratory screening on two FrontierMemory v1.0 tasks with a local model. Not a leaderboard submission. Protocol and deviations: `results/protocol-v3-official-like.md`. Memory construction and audit: `results/memory-v5-summary.md`.

## Setup

| Item | Value |
|---|---|
| Tasks | `build-word2vec-pipeline` (6 cases), `dapt-intrusion-detection-workflow-learning` (37 cases); original tasks and verifiers, fresh staged copy per trial |
| Task agent | Codex CLI 0.157.0-alpha.11.1, `--ephemeral`, web search disabled, inside Apptainer (`--containall --no-home`, only the trial workspace and a fresh per-trial Codex home bound) |
| Model | local `qwen3.8:27b-mtp-q4_K_M` via Ollama `/v1/responses`, 65,536 context, reasoning effort `medium` (reached 100% of requests) |
| Memory (B only) | frozen v5, official digest `94d59c2c…`, seeded into `$CODEX_HOME/memories/` as in the official `codex.py` (`MEMORY.md` also copied as `memory_summary.md`); `features.memories = true` in both arms |
| Order | A B B A A B within one job per task; same prompt template and tool set (7 tools) in both arms |
| Grading | unchanged verifier via Harbor; strict reward = all cases pass |

All 12 trials are valid: no timeout, no Harbor exception, every artifact collected or scored under D5'.

## Results

### Word2Vec (job 303008)

| # | Arm | Outcome | Strict | Cases / 6 | Agent s | Requests | Output tok |
|---|---|---|---|---|---|---|---|
| 1 | A | collection error: required callable missing | 0 | 0 | 422 | 13 | 17,387 |
| 2 | B | PASS | 1 | 6 | 149 | 11 | 5,849 |
| 3 | B | PASS | 1 | 6 | 342 | 13 | 14,352 |
| 4 | A | collection error: required callable missing | 0 | 0 | 546 | 21 | 21,377 |
| 5 | A | collection error: required callable missing | 0 | 0 | 241 | 13 | 8,952 |
| 6 | B | PASS | 1 | 6 | 101 | 8 | 3,823 |

**A 0/3, B 3/3 strict** (Fisher exact two-sided p = 0.10). B was faster (mean 197 s vs 403 s) and used fewer output tokens (8.0k vs 15.9k).

All three B agents opened the Word2Vec topic files from the memory folder. Each opened 4–5 files, among them the four Word2Vec-family topics listed in the index. No A agent found any memory; the A memory folder is empty.

### DAPT (job 303009)

| # | Arm | Outcome | Strict | Cases / 37 | Agent s | Requests | Output tok |
|---|---|---|---|---|---|---|---|
| 1 | A | tests failed | 0 | 22 | 571 | 13 | 18,585 |
| 2 | B | tests failed | 0 | 31 | 849 | 15 | 23,860 |
| 3 | B | tests failed | 0 | 31 | 478 | 13 | 14,528 |
| 4 | A | tests failed | 0 | 18 | 345 | 11 | 13,539 |
| 5 | A | tests failed | 0 | 16 | 886 | 15 | 33,704 |
| 6 | B | tests failed | 0 | 29 | 566 | 14 | 15,902 |

**Strict 0/3 in both arms. Cases passed: A mean 18.7 / 37, B mean 30.3 / 37.** Every B trial beat every A trial (Mann–Whitney exact two-sided p = 0.10, the smallest possible with n = 3 per arm).

**Mechanism not established.**
- No DAPT B agent ran a command that read the memory folder. None of them mentioned memory in its messages or reasoning.
- The DAPT topic file is not listed in the truncated index (see `memory-v5-summary.md`).
- Codex's native memory feature is built to put `memory_summary.md` (here a copy of the index) into the model context. Request bodies are not stored, so this is not verified per trial. If it holds, the B agents saw the cross-cutting lessons and 106 topic pointers, none of them for PCAP.
- The gain may come from the generic index lessons (verify, validate, check environment constraints) or may be noise. With n = 3 these cannot be told apart. The B agents did make IPv4/IPv6 and ICMP/ICMPv6 scope checks of the kind the unlisted topic describes. They never cited the topic, though, and A agents may make similar checks.

### Isolation check

One Word2Vec A agent searched the filesystem for benchmark files and queried its own Codex state databases.
- The search returned nothing, because the container only binds the workspace.
- The databases were empty, because each trial gets a fresh Codex home that is deleted afterwards.
- No trial accessed the repository, corpus, frozen memories, or verifier files.

## Memory ablation ladder on Word2Vec

Rows marked † used OpenHands with memory injected into the prompt. The v5 row is the official Codex `memories` mechanism. Same local model throughout.

| Memory | Construction | Compliant | A strict | B strict | B mean cases / 6 |
|---|---|---|---|---|---|
| v2 † | 14 family trajectories, truncated, custom prompt | no (task-selected) | 0/3 | 0/3 | 1.0 |
| v4 † | 14 family trajectories, official instruction | no (task-selected) | 0/3 | 1/3 | 4.3 |
| **v5** | **all 674 trajectories, official instruction, one memory for all tasks** | **yes (local model)** | **0/3** | **3/3** | **6.0** |
| v3 † | 14 family trajectories, custom "reference recipe" | no (upper bound) | 0/6 | 6/6 | 6.0 |

No-memory Word2Vec trials with the local model, on both harnesses: **0/15 strict**. Memory trials with protocol-faithful v5: 3/3.

## Findings

1. **Whole-corpus memory under the official rules matched the non-compliant upper bound on Word2Vec** (3/3 strict). This task depends on conventions from prior runs. v4 used the same instruction on a hand-picked family slice and got 1/3. More evidence gave more relevant, more consistent topic files than a curated slice did.
2. **On DAPT, memory raised the case pass rate a lot (18.7 → 30.3 of 37) but not the strict pass rate.** The no-memory baseline already gets partway; the remaining failing cases need exact metric definitions.
3. **Weak points of local-model memory generation showed up and are disclosed.**
   - The index call hit its output cap and left the DAPT topic unlisted.
   - One topic contains a full reference implementation, close to the rule against copying prior artifacts.
   - One topic makes a wrong library claim.
   - All three come from the memory model under the unchanged instruction.

## Caveats

- n = 3 per arm per task; two tasks; one local model. Both p-values are 0.10, the smallest possible at this n. Effects are consistent but under-powered.
- Not the leaderboard task model (GPT-6 Sol / Opus 5.5) and not the full 15-task suite.
- Temperature is not settable in Codex 0.157; the Ollama default was used in both arms.
- The verifier network mode is `public`; agent containers have no egress isolation, but web search is disabled and Ollama is the only model endpoint.
- Raw trajectories, memory text, agent workspaces and verifier output stay local.
