# Word2Vec protocol v2: Phase 3 smoke (Slurm job 301912)

Date: 2026-10-27. Sanitized counts and status only. Trajectories, workspaces, prompts,
verifier output, memory text, and Ollama request bodies stay local under
`results/word2vec-openhands/ab-v2/job-301912/` (git-ignored). Egress isolation was not enforced
(Harbor Singularity limitation; verifier network_mode staged as `public`).

## Job

- Runner: `slurm/run-word2vec-ab-v2.sbatch`, `TRIAL_ORDER="A"` (one no-memory trial).
- Model `qwen3.8:27b-mtp-q4_K_M`, context 65,536 (API-confirmed), temperature 0.1,
  reasoning_effort `medium`, OpenHands SDK 1.58.2, Harbor 0.24.0.
- `max_iterations=200`; task agent timeout 1200 s (multiplier 1.0).
- Slurm: `vcggpu`, 2x RTX 3090. sacct state COMPLETED, exit 0:0, elapsed 00:11:15.
- Base prompt-template sha256 `cc02f24b1613c1645ef1d124e1f76f30e6b85e82ebd30099cdf27b9328d14a6f`
  (final template for A is identical, no memory appended).

## Trial 1, condition A

| Field | Value |
|---|---|
| trial index / condition | 1 / A |
| `/workspace/solution.py` present (persisted workspace) | yes |
| Harbor artifact collection status | ok |
| verifier collected / passed / failed / errors | 0 / 0 / 0 / 1 |
| reward | 0.0 |
| status | INVALID (collected = 0) |
| agent wall time | 600 s by recorded timestamps (see uncertainties) |
| trial wall time | 644 s |
| termination reason | timeout (Harbor AgentTimeoutError, 1200 s) |
| model requests (Ollama request bodies) | 38, all with reasoning_effort = medium |
| agent steps (trajectory) | 43 |
| input / cached input / output tokens | 891,046 / 852,691 / 21,290 (OpenHands trajectory totals) |
| file-edit actions | 12 |
| test or python executions | 15 (terminal actions total 29) |
| Harbor exit code | 0 |

## Gate verdict: FAIL

- The agent produced `/workspace/solution.py`, but the verifier collected 0 cases. The single
  collection error was a task-contract mismatch (required callable absent from the module),
  not an infrastructure failure. The verifier container, test-file hashes, and staging all
  passed their preflights.
- The Phase 3 rule permits one identical resubmission only when the agent did not produce the
  file. That clause does not apply here, so no resubmission was made. Under the instruction to
  stop if the smoke still fails, Phase 4 was not started and no further GPU jobs were submitted.

## Uncertainties to resolve before Phase 4

- Harbor reports `AgentTimeoutError` after 1200.0 s, but the recorded agent execution interval
  and the trajectory's first and last timestamps span about 600 s. The cause is unresolved. The
  timeout stop rule must be understood before any A/B trial relies on it.
- Model requests (38 Ollama request dumps) differ from agent steps (43). The request-dump count
  is a proxy.
- Harbor left token fields null after the timeout. Totals come from the OpenHands trajectory
  `final_metrics` and are recorded with `token_source`.
- The 2400 s per-trial hang guard was not triggered and is not a per-trial stop decision.
