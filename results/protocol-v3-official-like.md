# Protocol v3: official-like FrontierMemory screening (2026-10-28)

Goal: a memory vs no-memory result that follows the FrontierMemory v1.0 rules (`frontiermemory/docs/rules.md`) wherever the local cluster allows it, plus an ablation over memory construction. Exploratory screening only. Not a leaderboard submission.

## Rules kept from the official protocol

| Rule | How it is met |
|---|---|
| Memory agent sees only the corpus, with no task map | All 674 pinned `joint-674-v1.0` trajectories. No selection by task. No task, verifier, repo, or notes in context |
| Generic prompt is `instruction.md`, unchanged | `frontiermemory/src/frontier_memory/dream_task/instruction.md` is embedded verbatim (sha256 recorded) |
| One memory for all target tasks | Memory v5 is generated once and frozen, then used on every evaluated task |
| No web search during generation | Local Ollama only, inside a Slurm job |
| Memory format | `MEMORY.md` present, UTF-8, no dotfiles or symlinks, at most 8 MiB (checked) |
| Task agent is a fixed harness, memory loaded natively | Codex CLI. B gets the memory as Codex's native global `AGENTS.md`; A has none |
| 3 attempts per task, same model and effort for A and B | k=3 per arm per task; A/B interleaved within one job |
| Original tasks and verifiers; infra failures rerun, not scored | Unchanged sources, fresh staged copies, oracle-validated pipeline |

## Declared deviations

- **Memory harness:** a local map-reduce harness (per-trajectory notes, then hierarchical consolidation) around the verbatim instruction, not an interactive agent. The rules leave the memory agent's choice open.
- **Models:** local `qwen3.8:27b-mtp-q4_K_M` for memory generation and as the task model, through Ollama. The leaderboard requires GPT-6 Sol or Opus 5.5 as task model. Corpus data must stay on-cluster.
- **Task subset:** only tasks runnable on Harbor's Singularity backend (single container, no paid LLM judge). The APEX, AutomationBench and EnterpriseOps tasks are excluded.
- **Infrastructure:** Harbor Singularity exec-timeout wrapper; verifier network mode staged as `public`.

## Ablation ladder (memory construction)

All rungs are scored with the same harness on Word2Vec.

| Rung | Evidence | Prompt | Status |
|---|---|---|---|
| none | — | — | control |
| v2 | 14 family trajectories, per-step truncated | custom | done: 0/3 (OpenHands), 0/3 (Codex gpt-reserve) |
| v4 | 14 family trajectories, untruncated | official instruction verbatim | in progress |
| v5 | whole corpus (674) | official instruction verbatim | planned (protocol-faithful) |
| v3 | 14 family trajectories, untruncated | custom "reference recipe" from PASS runs | done: 3/3. **Non-compliant upper bound** (reconstructs prior final artifact) |

Primary result: v5 vs no memory, strict pass@3 per task.
