# awilix-release-tier-implicit: grading-path check

Date: 2026-10-29. CPU only: `slurm/check-awilix-implicit-oracle-collection.sbatch` (job **303255**, PASS). Earlier job 303245 (attempt 1) had the same oracle result; it failed only on a wrong assertion in the check (the nop patch is not empty, see below). Harbor 0.24.0, Singularity backend.

Images (built by `slurm/build-awilix-release-tier-images.sbatch`, job 303231):
- Agent `containers/awilix-release-tier-implicit-v2.sif` from `containers/awilix-release-tier-implicit-v2.def`: the official task image (`swe-bench-202605@sha256:c574...`), plus the release-tier fixture commit and the `frontier-memory-task-base` tag.
- Verifier `containers/awilix-release-tier-implicit-verifier-v2.sif` from the same official image, with the official `tests/` and the uid-0 `agent` alias (see deviations).
- The older `containers/awilix-release-tier-implicit.sif` (mars-base) is kept, unused by the check.

## Equivalence of the new agent image with the mars-base image

| Item | mars-base (`awilix-release-tier-implicit.sif`) | official-based (`-v2.sif`) |
|---|---|---|
| node / npm | v24.12.0 / 11.6.2 | v24.12.0 / 11.6.2 |
| HEAD and tag | fixture commit 0be9005, tag `frontier-memory-task-base` | same |
| `git ls-files` tree (hash) | 81ff9150... | 81ff9150... (identical) |
| `node_modules` names (hash) | 85fa2076... (318 entries) | same |
| `package.json` / `package-lock.json` (hash) | 66d8e7fc... / 5b5237af... | same |

The official image's working tree has a modified `package-lock.json` (from npm install at image build). Both images have it.

## Results (job 303255)

| Run | Patch (collected) | Regression (base tests) | Functional (new tests) | Preference gate | Reward |
|---|---|---|---|---|---|
| nop | `package-lock.json` only | 161 passed, 0 failed | 0 (new suite does not run) | 0 | 0 |
| oracle (Harbor oracle agent) | 6 files, 29,739 bytes | 161 passed, 0 failed | 23 passed, 0 failed, 1 skipped | 1 (pass) | 1 |
| scratch-nop (our collection) | same hash as oracle | identical | identical | identical | 1 |

Checks: nop reward 0 and no functional pass: pass. Nop patch limited to `package-lock.json`: pass. Oracle functional and regression all pass: pass. Scratch collection hash equals the local patch: pass. Scratch counts equal oracle counts: pass. Verdict PASS.

Cases for the case-fraction field: `cases_total` = 184 (regression 161 + functional 23). The one functional skip is a test the official suite marks as skipped; skipped tests are not cases, as in the cookie-store check.

Runner record (`trial-record` on the job-303255 oracle directory): `valid`, `PASS`, strict reward 1, 184/184.

## Deviations

- **D-awilix-1 (uid-0 alias).** `test.sh` and `original-test.sh` switch to the agent user with `runuser`. Under the cluster's root-mapped fakeroot namespace (no subuid range), the same ownership problem as cookie-store applies, so the verifier image aliases `agent` to uid/gid 0 (`containers/awilix-release-tier-implicit-verifier-v2.def`). Test files and scripts are unchanged. Same cluster workaround as D24.
- **D-awilix-2 (agent image).** The implicit agent image is rebuilt on the official digest that the task family uses, not on mars-base. Equivalence is shown above. The mars-base image is not used.
- **D-awilix-3 (nop patch).** The untouched repository yields a patch that changes only `package-lock.json`, because the official image's working tree has a modified lock file. The collect step captures it, so nop is not "empty" (the cookie-store expectation). Nop still scores 0 with no functional passes, and the official verifier applies the lock diff cleanly.
- **D-awilix-4 (fixture commit).** The agent image adds the release-tier fixture commit and tag, as the mars-base image did. The verifier recreates the tag if it is missing (official `test.sh` behaviour).

No test names, test contents, solution text, or verifier output are in this file. Counts, sizes, and hashes only.
