# cookie-store-compositional-changelog: grading-path check

Date: 2026-10-29. CPU only (`slurm/check-cookie-store-oracle-collection.sbatch`), Harbor 0.24.0 Singularity backend.
Agent image `containers/frontier-memory-cookie-store.sif` (unchanged). Verifier image `containers/frontier-memory-cookie-store-verifier-v2.sif`, built from the amended `containers/frontier-memory-cookie-store-verifier.def` (the v1 SIF is kept, unused). Official `tests/test.sh`, `original-test.sh` and the preference verifier are unchanged. Final job: **303213, state FAILED** (the summary check did not pass, see below). Earlier attempts: 303207, 303210, 303212.

## Result of the final attempt (303213)

| Run | Patch bytes | Functional (new tests) | Regression (base tests) | Preference gates | Reward |
|---|---|---|---|---|---|
| nop (empty workspace) | 0 | not run (verifier exits early on an empty patch) | not run | not run | 0 |
| official solution (Harbor oracle agent) | 23,099 | 115 passed, 0 failed, 0 errors | 1284 passed, 0 failed, **1 error**, 4 skipped | 2 pass, 2 fail (score 0) | 0 |
| solution applied in scratch copy, collected by our runner, graded via nop | 23,099 (same hash) | identical to oracle | identical to oracle | identical to oracle | 0 |

Checks: nop reward 0 with empty patch: pass. Oracle functional all pass: pass. Oracle regression all pass: **fail** (the one error, below). Scratch collected patch equals local patch: pass. Scratch counts equal oracle counts: pass.

**cases_total derived from the oracle run:** 1400 (regression 1285 = 1284 passed + 1 error; functional 115). The 4 skipped regression tests are not counted as cases.

## Open problem: one regression error in the verifier environment

The one baseline error is `OSError: The temporary directory /tmp/pytest-of-agent is not owned by the current user` raised at test setup. It is an environment fault, not a solution fault: the solution passes all 115 functional cases and the baseline run is otherwise clean. Setting `TMPDIR` in the staged `[verifier.env]` (the attempt 4 change) did not change pytest's temp root, so the verifier still uses `/tmp`. Next step for the lead: give the verifier a writable temp root that the agent user owns, or otherwise clear the stale `/tmp/pytest-of-agent` in the verifier container, and rerun. The rerun is not done (4-attempt limit).

## Fixes made to get this far (grading path only; verifier files unchanged)

1. `containers/frontier-memory-cookie-store-verifier.def`: `%files` copies into directories the base image already has, which nested the copies as `/app/tests/tests` and `/app/.git/.git`. `%post` now removes the nested duplicates and checks that `git status` is clean. Built as `-v2.sif`.
2. Staged `task.toml` (the copy in `build/`, not the official task): `[verifier.env]` gets `GIT_CONFIG_COUNT/KEY_0/VALUE_0` = `safe.directory=*`. Without it, git run by the agent user rejects `/app` (owned by the Harbor user), so the reset step cannot restore `tests/conftest.py` and `test.patch` fails to apply. This is the only change outside the image.
3. Staged `task.toml`: `TMPDIR` set to a per-job directory. Did not take effect (see above).
4. `reward.txt` and `functional-reward.txt` are used instead of `reward.json`. The verifier writes no per-case JSON, so case counts come from pytest summary lines in `verifier/test-stdout.txt`, in the order `base` (regression) then `new` (functional).

## Earlier attempts (all FAILED, for the record)

- 303207: verifier v1 image. Oracle `test.patch` failed to apply (nested test copy and git safe.directory). Summary step expected `reward.json`.
- 303210: nested copies removed (v2 image). Still `test.patch` failed to apply (git safe.directory for the agent user).
- 303212: env fix applied. `test.patch` applied; baseline run had the one pytest temp-dir error (exit 1, reward 0).
- 303213: `TMPDIR` added; same error. Final.

No test names, test contents, verifier output, or solution text are copied into this file. Patches and verifier output stay in `jobs/` and `build/` (gitignored). Run directory `results/cookie-store-oracle-check-303213/` holds counts, sizes, and hashes only (gitignored: add `/results/cookie-store-oracle-check-*/` to `.gitignore`, which is outside this task's files).

## Lead follow-up (job 303216, 2026-10-29)

Attempt 5 set the verifier environment to `USER`/`LOGNAME=root`, together with the `safe.directory` setting. Its results:
- **Functional:** the oracle passes 115/115.
- **Regression:** 1284 passed, 4 skipped, 1 error.
- **Preference gates:** 2 pass, 2 fail. That is expected for the reference solution, by design.

The remaining error has the same cause as before: pytest raises `tmp_path root ... not owned by the current user`.

**Root cause, verified directly.** The cluster account has no `/etc/subuid` entry, so Apptainer `--fakeroot` falls back to a root-mapped namespace in which only uid 0 is mapped. After `runuser -u agent`, the process has uid 10001, but files it creates are owned by uid 0. A one-line test inside the verifier SIF shows `id -u` = 10001 and `stat` of a new directory = 0. pytest's ownership check on its temp root therefore fails for any test using `tmp_path`, whatever the patch.

This is an environment fault that affects every arm and the official solution equally. It cannot be fixed without changing the verifier or the cluster's user-namespace configuration.

**Status: cookie-store is NOT validated.** Under preregistration §3 it stays excluded unless the grading path is fixed by Nov 5. The proper fix is a subuid/subgid range for the account, granted by the cluster admin.
