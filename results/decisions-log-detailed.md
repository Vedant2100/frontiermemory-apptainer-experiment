# Detailed decisions log (append-only)

Lower-level protocol, infrastructure and analysis decisions. Big-picture decisions are in `/home/csgrad/vbork001/decisions-timeline.md`. Status: ✅ adopted, ❌ rejected or withdrawn, ⏳ pending.

| # | Date | Decision | Status | Reference |
|---|---|---|---|---|
| D1 | 2026-10-28 | Harbor Singularity exec has a hard 600 s timeout; work around it with a wrapper that sets a default timeout (7200 s) | ✅ | `scripts/harbor_singularity_exec_timeout.py` |
| D2 | 2026-10-28 | Validity rule D5': agent-caused failures (no artifact, collection error, failed tests) score 0; only infrastructure faults are INVALID. Amended before any B trial; disclosed | ✅ | `results/word2vec-openhands/protocol-v2.md` |
| D3 | 2026-10-28 | Grade with Harbor's `nop` agent on a pre-populated workspace, using the unchanged verifier, and validate against the oracle for each task | ✅ | Oracle checks for Word2Vec and DAPT |
| D4 | 2026-10-28 | Trial order A B B A A B within one job; A and B identical except for memory | ✅ | — |
| D5 | 2026-10-28 | Do not route gated corpus data or memories to OpenAI. The Codex gpt-reserve memory generation was blocked by the permission classifier and not worked around | ✅ | — |
| D6 | 2026-10-28 | v4 ladder rung: hand-picked family slice plus the official instruction (1/3). Later labeled non-compliant because selection was by task | ✅ | `ab-v4-results.md` |
| D7 | 2026-10-28 | v5 memory harness: local map-reduce (per-trajectory notes, then topic groups, reduce, index) around the verbatim instruction | ✅ | `scripts/generate_corpus_memory_v5.py` |
| D8 | 2026-10-29 | Codex runs inside Apptainer (`--containall --no-home`) with a fresh Codex home per trial; isolation verified from traces | ✅ | `ab-v5-results.md` |
| D9 | 2026-10-29 | Remove the verifier's callable name from tracked reports | ✅ | Commit `3782ff1` |
| D10 | 2026-10-29 | DAPT replication (k=6 per arm) instead of claiming the first k=3 gain | ✅ | Job 303129: gain not replicated |
| D11 | 2026-10-29 | M3 = v5 plus a mechanically appended complete topic list. Disclosed as built after seeing the v5 DAPT result | ✅ | `memory/frozen-v5-fullindex`, `4a2eb528…` |
| D12 | 2026-10-29 | Patch-artifact mode in the runner; cattrs is the first patch task | ✅ | Commit `10a810e` |
| D13 | 2026-10-29 | cattrs oracle: the reference solution scores 76/77 because the user-preference check is memory-dependent by design. The grading path is accepted as valid | ✅ | `results/cattrs-oracle-check-summary.md` |
| D14 | 2026-10-29 | The lead saw the preference criteria in a verifier report while debugging. Rule: never use them in any prompt, memory or code | ✅ | Same file |
| D15 | 2026-10-29 | Each Slurm job runs a per-job snapshot of the runner script, after a mid-run edit risk was found | ✅ | `slurm/run-codex-ollama-trial.sbatch` |
| D16 | 2026-10-29 | Stage agent and verifier `network_mode` as `public`, but only where declared, because Singularity rejects `no-network` | ✅ | `scripts/stage_word2vec_task_for_apptainer.py` |
| D17 | 2026-10-29 | R25: stratified random 25% (168 trajectories; 46 PASS, 122 FAIL), seed 2027, reusing map notes | ✅ | Selection sha `24d2518c…` |
| D18 | 2026-10-29 | Governor judge: a non-Qwen local model preferred; gemma3:27b downloaded (17.4 GB) | ✅ | — |
| D19 | 2026-10-29 | Governor validation v0 failed (sensitivity 0.12, specificity 0.92). G and GR not run | ✅ | `results/governor-validation-summary.md` |
| D20 | 2026-10-29 | Prereg amendment A1: validate on detectable perturbations only; one prompt revision; choose between gemma3 and qwen3.8 by validation; judge technical units only. If no judge passes, drop G and GR | ✅ | `results/preregistration-v1.md`, commit `c74e64f` |
| D21 | 2026-10-29 | cookie-store: the `USER`/`LOGNAME=root` fix failed. Root cause: no subuid, so fakeroot maps only root. The test is not edited; the task is excluded unless the admin fixes it | ✅ | `results/cookie-store-oracle-check-summary.md` |
| D22 | 2026-10-29 | Governor outputs and cookie-store oracle outputs are git-ignored | ✅ | `.gitignore` |
| D23 | 2026-10-29 | Multi-arm runner: `MEMORY_ARMS` plus a balanced Latin order (`A0 R25 M3 G GR …`, 15 trials per task) | ✅ | Uncommitted; lead review pending |
| D24 | 2026-10-29 | cookie-store subuid workaround: verifier image v3 aliases `agent` to uid/gid 0, so ownership stays consistent under the root-mapped fakeroot namespace. Tests unchanged; declared as a deviation. Accepted only if the oracle check passes all functional and regression cases | ⏳ | `containers/frontier-memory-cookie-store-verifier-v3.def`, build job 303228 |
| D25 | 2026-10-29 | D24 outcome: oracle check 303229 PASS (functional 115/115, regression 1285/1285, preference gates fail by design). cookie-store re-included as a candidate task with verifier image v3 | ✅ | `results/cookie-store-oracle-check-summary.md` |
| D26 | 2026-10-29 | A1 validation: gemma3 sensitivity 0.16 / specificity 0.85; qwen3.8 0.21 / 0.98. Both fail; no judge chosen | ✅ | Jobs 303219, 303220 |
| D27 | 2026-10-29 | Prereg A2: grounding governor (token-in-evidence), same validation sets, no revisions | ✅ | `results/preregistration-v1.md` |
| D28 | 2026-10-29 | A2 validation: sensitivity 0.62, specificity 0.50 (fail). 50 of 100 original cited lessons lack their own identifiers in the cited steps; truncation explains only 9 of them | ✅ | `results/governor-run-a2-validate/` |
| D29 | 2026-10-29 | Prereg A3: arms A0/R25/M3, k=5, Latin order of 5 rounds; extended audit; deterministic scope-leakage tagging from topic file names and task names only | ✅ | `results/preregistration-v1.md` |
| D30 | 2026-10-29 | awilix implicit and explicit: oracle PASS (jobs 303255, 303256), 184 cases. Changes: uid-0 agent alias in the verifiers; implicit agent image rebuilt on the official digest (equivalence checked); the nop check allows a patch that touches only package-lock.json | ✅ | `results/awilix-release-tier-*-oracle-check-summary.md` |
| D31 | 2026-10-29 | cookie-store and both awilix tasks added to the runner | ✅ | — |
| D32 | 2026-10-29 | customer-delivery: oracle PASS (job 303268), 188 cases, preference 3/3; uid-0 alias in the verifier; official agent image unmodified. The patch preflight fallback fixes a cattrs preflight bug introduced in `a8d83df` (job 303198 ran an earlier snapshot, so it was not affected) | ✅ | `results/customer-delivery-oracle-check-summary.md` |
| D33 | 2026-10-29 | GPU smoke test: one A0 trial each on cattrs, cookie-store, awilix-implicit, awilix-explicit and customer-delivery before the confirmatory matrix. Exploratory only, not pooled | ✅ | — |
| D34 | 2026-10-29 | R25 frozen: digest `75be173f…`, 116 topics | ✅ | `results/memory-r25-summary.md` |
| D35 | 2026-10-29 | GPU serialization: all GPU jobs use `--job-name=fm-serial --dependency=singleton` (one 2-GPU job at a time). Smoke jobs 303272 and 303273 were cancelled after about 15 min and resubmitted as 303285 and 303286; queued jobs 303274–303276, 303281 and 303282 were moved into the singleton queue. CPU-only jobs are not limited | ✅ | Timeline #34 |
| D36 | 2026-10-29 | Integrity check of DAPT jobs 303129 and 303133 after the mid-run runner edit: the edit reached later trials but changed only an `arm` metadata field. Prompt, config and memory digests are consistent, so both jobs are kept as exploratory data | ✅ | `results/ab-v5-results.md` addendum |
| D37 | 2026-10-29 | cattrs exploratory A vs v5 (303198): 0/6 strict both arms; cases A 76/76/73, v5 10/76/76. Reported as exploratory; the preregistered cattrs comparison is the A0/R25/M3 matrix | ✅ | Same |
