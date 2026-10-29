# customer-delivery-contextual-preferences: grading-path check

Date: 2026-10-29. CPU only: `slurm/check-customer-delivery-contextual-preferences-oracle-collection.sbatch`, job **303268**, PASS on attempt 1 of 4. Harbor 0.24.0, Singularity backend.

Images (`slurm/build-customer-delivery-contextual-preferences-images.sbatch`, job 303260):
- Agent `containers/customer-delivery-contextual-preferences.sif`: the official task image by digest (`swe-bench-202605@sha256:748294a8...`, tag `kh70...-v1.1`), unmodified. Checked at build: HEAD 82ac179, clean `git status`, `node_modules` present, `/opt/jest-ctrf` reporter present, `core.hooksPath=/dev/null`. Node v24.12.0, npm 11.6.2.
- Verifier `containers/customer-delivery-contextual-preferences-verifier.sif`: the same image plus the official `tests/` directory and the uid-0 `agent` alias (deviation below).
- Apptainer rejects a reference that carries both a tag and a digest, so the defs use the digest only.

## Results (job 303268)

| Run | Patch | f2p (functional, 26) | p2p (regression, 162) | Preference (CTRF) | Reward |
|---|---|---|---|---|---|
| nop | empty (0 bytes) | 0/26 | 162/162 | 0/3 | 0 |
| oracle (Harbor oracle agent) | 25,057 bytes | 26/26 | 162/162 | 3/3 | 1 |
| scratch-nop (our collection) | same hash as oracle | 26/26 | 162/162 | 3/3 | 1 |

Checks: nop reward 0, empty patch, no functional pass; oracle f2p and p2p all pass; scratch collection hash equals the local patch; scratch counts equal oracle counts. Verdict PASS.

`cases_total` = 188 (f2p 26 + p2p 162). The p2p whitelist includes the synthetic `[gate] npm run build` id, which is counted as a case, as the grader does.

Runner record (`trial-record` on the job-303268 oracle directory): PASS, strict reward 1, 188/188, preference 3/3.

## Deviations

- **uid-0 alias.** `test.sh` uses `runuser -u agent`. The verifier image aliases `agent` to uid/gid 0, the same cluster workaround as cookie-store v3 and the awilix verifiers. Test files are unchanged.
- No `[verifier.env]` additions (not needed; the oracle passed).

Counts, sizes, and hashes only. No test names, test contents, solution text, or verifier output.
