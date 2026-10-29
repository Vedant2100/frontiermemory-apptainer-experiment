# cattrs-compositional-changelog: grading-path check (Slurm job 303194)

Date: 2026-10-29. CPU only, Harbor 0.24.0 Singularity backend, unchanged verifier. Agent and verifier images: `containers/frontier-memory-cattrs{,-verifier}.sif`.

| Run | Patch bytes | Functional (f2p) | Regression (p2p) | Cases / 77 | Strict reward |
|---|---|---|---|---|---|
| nop (empty workspace) | 0 | 0/70 | 7/7 | 7 | 0 |
| official solution (Harbor oracle agent) | 24,810 | 69/70 | 7/7 | 76 | 0 |
| official solution applied in scratch copy, collected by our runner, graded via nop | 24,810 (identical hash) | 69/70 | 7/7 | 76 | 0 |

**Reading.** The one check the official solution fails is the task's *user-preference* check. That is the part of this task that must come from prior runs, which is to say from memory. The reference solution implements only the functional change. So the grading path is valid:
- an empty patch scores the regression cases only;
- the reference passes every functional and regression case;
- our runner's patch collection is byte-identical to Harbor's.

A strict pass on this task needs the preference that prior runs carried.

**Hygiene.** While debugging, the lead saw the names of the failing preference criteria in the verifier report. That information is not used in any prompt, memory, or runner code. Memory versions remain frozen as generated.

**Staging deviations** (same as the other tasks): the agent and verifier `network_mode` are staged as `public`, because Harbor's Singularity backend rejects `no-network`. Web search stays disabled in Codex, and Ollama is the only model endpoint.
