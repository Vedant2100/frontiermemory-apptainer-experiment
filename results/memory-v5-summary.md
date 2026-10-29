# Memory v5: whole-corpus memory under the official instruction (jobs 302131–302136)

Date: 2026-10-28. This is the protocol-faithful rung of the memory ladder (`results/protocol-v3-official-like.md`). Memory text, notes and trajectories stay local; this file reports counts and hashes only.

## Construction

| Item | Value |
|---|---|
| Evidence | All 674 trajectories of `joint-674-v1.0` (corpus digest `c7d31214…`). No task map, no selection by target task |
| Instruction | `frontiermemory/src/frontier_memory/dream_task/instruction.md` verbatim (sha256 `a96e69af…`) in every map, reduce and index prompt |
| Model | local `qwen3.8:27b-mtp-q4_K_M` through Ollama, inside Slurm; no web, no external API |
| Map | 4 shards (jobs 302131–302134), one note per trajectory, 674/674 ok, 900-token output cap. 632 notes hit the cap |
| Group | 455 normalized topic labels merged into 324 groups (213 singletons, largest 35 notes) |
| Reduce | job 302136, one topic file per group, 324/324 ok. 21 truncated at the output cap. 4.0 h wall |
| Index | one call writes `MEMORY.md` from the topic outlines |

## Frozen artifact

| Item | Value |
|---|---|
| Location | `memory/frozen-v5/` (git-ignored, read-only) |
| Official `check_memory` | ok, no errors |
| Folder digest (official `memory_sha256`) | `94d59c2cadff4b52f6f544cc82672744dc271f7fa3d31997aad76d8801f4fa92` |
| `MEMORY.md` sha256 | `100f84c5…`, 16,371 bytes |
| Files / total bytes | 325 / 1,289,678 (limit 8 MiB) |
| Citations (informational) | 2,952 total, 99.5% resolve to an existing step |

## Lead audit (done before any v5 trial result was seen)

- **Index truncated.** The index call stopped at its 4,096-token cap. `MEMORY.md` lists 106 of the 324 topic files. All four Word2Vec-family topics are listed. The PCAP/DAPT topic is in `topics/` but **not in the index**. Codex sees the whole folder, so the agent can still find it, but less easily. v5 was frozen as generated, not repaired.
- **Relevant content exists for both evaluated tasks.**
  - Word2Vec: four topic files cover preprocessing, gensim 4.x usage, `min_count`, and the interface-discovery lesson.
  - DAPT: one topic file lists the metric-scope and flow-counting rules that earlier FAIL runs violated.
- **Compliance flags (disclosed, not edited).** The official instruction forbids copying final answers or prior final artifacts.
  - One Word2Vec topic contains a complete reference implementation of the entry point.
  - The DAPT topic quotes one concrete intermediate count from a prior run as an example of a double-counting error.
  - These were written by the memory model under the unchanged official instruction. No researcher-written prompt asked for them. They are reported as a limitation of local-model memory generation.
- **Known errors.** One Word2Vec topic gives an incorrect gensim 4.x claim: that the constructor cannot train directly. Other topics contradict it.

## Evaluation

Main A/B: v5 vs no memory, Codex CLI + local Qwen3.8 through the official `$CODEX_HOME/memories` mechanism, k=3 per arm, order A B B A A B.
- Word2Vec: job 303008
- DAPT: job 303009

Results will be added to this file.
