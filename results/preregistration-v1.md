# Preregistration v1: memory construction and governance on FrontierMemory (confirmatory matrix)

Status: DRAFT. It is frozen when committed with the tag `prereg-v1`, before any confirmatory trial runs. Any later change is a dated amendment at the bottom.
Target: FORGE 2027 Data & Benchmarking track. Exploratory results so far (`ab-v5-results.md`, the ladder) are labeled exploratory and are **not** pooled with this matrix.

## 0. Principle: every memory arm is built by software, not by a person

No arm involves a researcher choosing, editing, or filtering evidence or lessons. Each arm is fully specified by the following, all committed before trials:
- the frozen corpus (`joint-674-v1.0`, digest `c7d31214…`);
- the official instruction (`dream_task/instruction.md`, sha `a96e69af…`);
- a model and its settings;
- code with fixed parameters and seeds.

No construction step sees the target tasks, their instructions, verifiers, or solutions, or any task outcome. The earlier hand-picked slices (v2, v3, v4) were chosen by target-task keyword. They stay in the exploratory record only.

## 1. Arms

| Arm | Construction | Contrast it serves |
|---|---|---|
| **A0** | No memory | Control |
| **R25** | Random 25% of the corpus: 168 trajectories, sampled with seed 2027, stratified to keep the PASS/FAIL ratio. Same map notes (reused, because map is per-trajectory), same group, reduce and index code as M3 | Evidence breadth (H1) |
| **M3** | Whole corpus: v5 topics plus a deterministic complete index (`memory/frozen-v5-fullindex`, digest `4a2eb528…`) | Reference memory |
| **G** | M3 passed through the automated governor (§2) | Governance (H2) |
| **GR** | M3 with the *same number* of units removed as G, chosen uniformly at random (seed 2027) from the same eligible units, with the same reassembly | Size-matched control for G (H3) |

**M2** (v5 as generated, with the truncated index) is not a confirmatory arm. M2 versus M3 is reported only as an exploratory discoverability check.

Every arm uses the same reassembly and index code. Every arm must pass the official `check_memory` and is frozen read-only with its digest before trials.

## 2. The governor (arm G): a software pipeline

The governor is part of memory generation, so it follows the same rules: it sees only the corpus, uses no web, and never sees a task map. It takes M3 and the corpus as inputs and outputs a memory folder.

1. **Segmentation** (deterministic parser, no model). Each topic file is split into *units*: a heading, bullet, numbered item, paragraph, or fenced code block. Headings are structural and are never removed. The parsed citations (`inputs/tNNNN.json#step=K`) are attached to each unit.
2. **Rule R-artifact** (deterministic). A fenced code block of more than 12 non-blank lines is removed. This operationalizes the official instruction's ban on reproducing prior final artifacts. The threshold is fixed here.
3. **Evidence retrieval** (deterministic).
   - A unit with resolvable citations gets its cited steps as evidence.
   - Otherwise it gets the top-3 steps by BM25 over the trajectories in the unit's topic group (from `groups.json`).
   - Each step is truncated to 2,000 chars, and each step's trajectory outcome (PASS or FAIL) is included.
4. **Evidence judge** (model). The prompt is fixed and committed before running. It receives the unit, the evidence and the outcomes, and outputs JSON with a `verdict`: `supported`, `contradicted`, or `insufficient`.
   - **Judge model:** an open model from a *non-Qwen* family of 20–35B parameters, run locally through Ollama at temperature 0. The exact tag and digest are recorded at freeze.
   - **Fallback:** if none can be obtained by Nov 3, the fallback is `qwen3-coder:30b`. The model-family correlation is then declared.
5. **Admission rule (primary).** A unit is dropped if its verdict is `contradicted`, or if R-artifact removed it. Everything else is kept.
   - **Separation rule, decided before seeing any trial:** if the primary rule removes fewer than 5% of non-heading units, the strict rule is applied instead. The strict rule also drops `insufficient` units that contain a concrete technical assertion (a number, an identifier in backticks, or a command).
   - The governor's unit counts are reported either way. This prevents the earlier failure mode, where the governed and ungoverned arms were nearly identical.
6. **Reassembly** (deterministic). Each topic file is rebuilt from its kept units in their original order. A file left with only headings is dropped. The complete index is regenerated with the same code as M3.

**Judge validation** (automatic, before freeze, with no human labels and no task data):
- Synthetic contradictions are made from 100 units sampled from M3. Each is perturbed by a fixed perturbation script: a changed number or flag, a swapped identifier, or a negated directive. These are judged against the original evidence.
- Sensitivity is the share of perturbed units judged `contradicted`. Specificity is the share of the 100 unperturbed units judged `supported` or `insufficient`.
- **Gate:** sensitivity ≥ 0.6 and specificity ≥ 0.8. If the gate fails, the prompt may be revised **once**, and only on this synthetic set. Both attempts are reported.

## 3. Tasks and trials

- **Tasks:** the locally runnable official v1.0 tasks whose grading path passes an oracle check by **Nov 5**. Candidates are build-word2vec-pipeline, dapt-intrusion-detection-workflow-learning, cattrs-compositional-changelog, cookie-store-compositional-changelog, awilix-release-tier-implicit, awilix-release-tier-explicit, and customer-delivery-contextual-preferences. A task that is not validated by Nov 5 is excluded, and the reason is reported.
- **Task agent:** Codex CLI 0.157.0-alpha.11.1, with the official `$CODEX_HOME/memories` mechanism, `features.memories=true` in every arm, and web search off. The model is local `qwen3.8:27b-mtp-q4_K_M` with 65,536 context and effort `medium`.
- **Trials:** k = 3 per arm per task, fresh workspace each time. There is one job per task. Within a job, arm order follows a fixed balanced sequence of 15 trials (3 rounds of a Latin rotation of A0, R25, M3, G, GR) and is committed.
- **Validity:** infrastructure failures (a Harbor exception, no grading, or an infra timeout) are rerun at the end of the same job and not scored. Agent-caused failures score 0 (D5'). No other exclusions.

## 4. Outcomes and analysis

- **Primary outcome:** strict pass (verifier reward = 1) per trial.
- **Secondary outcomes:** fraction of cases passed; agent wall time; output tokens; whether the agent read the memory folder (from the trace).
- **Primary contrasts** (Holm-corrected across the three):
  - **H1 (breadth):** M3 > R25.
  - **H2 (governance):** G is not worse than M3. Non-inferiority margin: −1 strict pass in total across all tasks. Superiority is reported if present.
  - **H3 (governance versus removal):** G > GR.
  - **H0** (M3 > A0) is reported as the benchmark-validity check.
- **Tests:** exact paired sign-flip permutation over tasks, applied to the per-task difference in strict pass rate, with a secondary run on the case fraction. Pooled counts and per-task tables are shown for every arm.
- **Power caveat, stated in advance:** with about 5–7 tasks × 3 trials, only large effects are detectable. The paper reports effect sizes with exact intervals and does not claim equivalence from a null.

## 5. Memory-quality audit (measurement, not construction)

Run automatically on every arm's frozen memory:
- unit counts;
- code-block units longer than 12 lines;
- the judge's verdict distribution;
- the share of units with resolvable citations.

This audit does not feed back into any arm.

## 6. Declared deviations from the official protocol

- **Task model:** local Qwen, not GPT-6 Sol or Opus 5.5.
- **Task subset:** local tasks only.
- **Memory generation time:** the map and reduce wall time on local GPUs is about 7 h, against the official 6 h limit.
- **Network modes:** staged as `public`, because Harbor's Singularity backend rejects `no-network`.
- **Prompt header:** the runner's "Required output artifacts" header is added.
- **Memory map notes:** reused across R25, M3, G and GR, which is equivalent to rerunning the per-trajectory map.

## Amendments
(none)
