# awilix-release-tier-explicit: grading-path check

Date: 2026-10-29. CPU only: `slurm/check-awilix-explicit-oracle-collection.sbatch` (job **303256**, PASS). Earlier job 303246 (attempt 1) had the same oracle result; it failed only on the same wrong nop assertion fixed for implicit. Harbor 0.24.0, Singularity backend.

Images (`slurm/build-awilix-release-tier-images.sbatch`, job 303231):
- Agent `containers/awilix-release-tier-explicit.sif` from `containers/awilix-release-tier-explicit.def`: the official task image named in `task.toml` (`swe-bench-202605@sha256:c574...`), used unmodified (HEAD 82ac179, node_modules present, node v24.12.0, npm 11.6.2).
- Verifier `containers/awilix-release-tier-explicit-verifier.sif` from `containers/awilix-release-tier-explicit-verifier-v2.def`: the same official image with the official `tests/` and the uid-0 `agent` alias (see deviations).

## Results (job 303256)

| Run | Patch (collected) | Regression (base tests) | Functional (new tests) | Preference gate | Reward |
|---|---|---|---|---|---|
| nop | `package-lock.json` only | 161 passed, 0 failed | 0 (new suite does not run) | 0 | 0 |
| oracle (Harbor oracle agent) | 6 files, 29,739 bytes | 161 passed, 0 failed | 23 passed, 0 failed, 1 skipped | 1 (pass) | 1 |
| scratch-nop (our collection) | same hash as oracle | identical | identical | identical | 1 |

Checks: all pass, verdict PASS. Collected patch hash matches the scratch patch. `cases_total` = 184 (161 + 23), the functional skip is excluded as in the implicit check.

Runner record (`trial-record` on the job-303256 oracle directory): PASS, strict reward 1, 184/184.

## Deviations

- **D-awilix-1 (uid-0 alias).** `test.sh` and `original-test.sh` use `runuser -u agent`, so the verifier image aliases `agent` to uid/gid 0 (same cluster workaround as cookie-store v3). Test files unchanged.
- **D-awilix-3 (nop patch).** The official image's working tree has a modified `package-lock.json`, so the nop collect step yields a lock-file-only patch. Nop still scores 0 with no functional passes.

Counts, sizes, and hashes only. No test names, test contents, solution text, or verifier output.
