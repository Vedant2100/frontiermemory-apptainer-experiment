# Corpus v1.0 → v1.1 audit (2026-10-30)

FrontierMemory moved the corpus to v1.1 on Oct 29: 750 trajectories (256 PASS, 494 FAIL), up from 674 (184 PASS) in v1.0. The changelog says the update is meant "to prevent reward hacking from metadata". Our confirmatory study stays on v1.0 (preregistered). This audit asks whether our v1.0 memories could have used the metadata that v1.1 removes.

## What v1.1 removed

- The Hugging Face commits are titled "v1.1: 750 sources without corpus-building metadata" and "v1.1: tNNNN session IDs, drop DreamBench metadata tags".
- In v1.0, **76 of 674** trajectory files carry message-level metadata such as `"schema": "dreambench-user-feedback-v1", "source": "dreambench-curation"` and `"schema": "dreambench-verifier-result-v1"`. These tags mark curated feedback messages and verifier-result messages. v1.1 has no such strings (0 files).

## Did any of it reach our memories?

**No.**

- `scripts/build_corpus_evidence_v5.py` renders only message text, tool calls and tool outputs. The metadata fields are never passed to the memory model.
- The only "dreambench" strings anywhere in our v5 and R25 pipelines are the git tag name `dreambench-task-base`, as it appeared in agents' own `git log` output:
  - v5: 3 evidence files, 3 notes and 1 topic file (the same topic is in M3);
  - R25: none.
- A tag name carries no task, verifier or answer information.

## Notes

- The official harness repo (`letta-ai/frontiermemory`, latest upstream) still pins `RELEASE_REVISION = "v1.0"` (digest `c7d31214…`). The v1.1 switch so far exists only on the website and Hugging Face.
- The dataset card gives v1.1's digest as `47641d5b…`. Both the `v1.1` tag and `main` currently hash to `19346a3e…`. This is reported as a discrepancy, not resolved.
- v1.1 is stored locally (git-ignored, gated) for building the leaderboard memory system.
