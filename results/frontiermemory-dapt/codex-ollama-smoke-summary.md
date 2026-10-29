# Codex CLI + local Ollama DAPT smoke (Slurm job 302375)

Date: 2026-10-28. One no-memory trial (condition A) on `dapt-intrusion-detection-workflow-learning`. No OpenAI or ChatGPT credentials were used. Raw trial outputs stay local under `results/frontiermemory-dapt/codex-ollama-job-302375/` (not committed).

## Result

| Item | Value |
|---|---|
| Verifier cases collected | 37 of 37 (gate: > 0, passed) |
| Verifier cases passed | 23 of 37 (14 failed, 0 errors) |
| Strict reward (Harbor) | 0.0 (raw 0.0) |
| Failure category | TESTS_FAILED (valid trial, not infra) |
| Agent wall time | 1309 s (timeout 5400 s, not timed out) |
| Codex exit | 0, 1 turn completed, 0 turns failed |
| Commands executed | 26 |
| Tokens (turn.completed) | input 669,858 (cached 581,881), output 43,770, reasoning-output not reported |
| Slurm job | 302375, COMPLETED, exit 0:0, elapsed 00:22:53 (partition vcggpu, 2 GPUs, 2h30 limit) |

## Harness and effort audit

| Item | Value |
|---|---|
| Harness | Codex CLI 0.157.0-alpha.11.1 in the DAPT agent SIF (`--containall --cleanenv --no-home`, no host home, no auth.json, no provider env vars) |
| Provider | custom `local_ollama` Responses provider at `127.0.0.1:<job port>` (probe chose `responses-custom-provider`) |
| Model | `qwen3.8:27b-mtp-q4_K_M`, Ollama 0.40.11, 65,536 context loaded before and after the trial |
| Reasoning effort | `medium` in 28 of 28 `/v1/responses` request bodies |
| Temperature | Not settable in Codex; Ollama default (not recorded in request bodies) |
| Memory | None (condition A). `memory_sha256` null |
| Prompt sha256 | `ec063198b92d1ac9518d071f4679a34dad35f447b6f8633e6957eece6383b349` |
| Codex config sha256 | `4d7da93ea6504e28fd255a7656d5e16f72e297d634907d3455292c3ae3119c08` |
| Runner harness sha256 | recorded in `harness-sha256.txt` (run folder, local) |

Preflight (container): host home not visible, `/root` entries present with `packets.pcap`, no auth.json, no OpenAI/Anthropic env vars, Ollama reachable from the container, `memories` feature on, all other listed features off. Provider probe: 1 turn, 1 HTTP 200 on `/v1/responses`.

## How /root persistence works

- The agent SIF is read-only. For each trial the runner tars the image's `/root` out of the image into a fresh host directory (`trial-1-A/root`), then checks it against a sha256 manifest computed inside the image (`preflight/image-root-sha256.txt`). The copy must match before Codex starts. The starting hash list is `trial-1-A/starting-files-sha256.txt`.
- That directory is bound at `/root` inside the agent container, with `--pwd /root` and `codex exec -C /root`. Codex's writes persist on the host, and the final hash list is `trial-1-A/final-files-sha256.txt`.
- Grading copies only the declared artifact (`/root/network_stats.csv`, start sha `ad1ebae7...`, final sha `f23ea778...`) and binds that single file at `/root/network_stats.csv` in the Harbor `nop` agent container. Harbor collects it from there and uploads it to the separate verifier container, as the DAPT oracle check does.
- The agent changed the artifact (start and final hashes differ), so `artifact_present` is true. The verifier's 23 passes (nop gave 0) show the agent's file reached the verifier.

## Job timeline and sacct

- Job 302375 started 17:59:54 and finished 18:22:47 (elapsed 22:53). The trial's Codex run took 1309 s, and Harbor grading ran in the final minute.
- Preflight, staging, and the provider probe finished before the trial started.
- One Harbor warning was logged: "Configured runtime overrides apply only to the agent environment". This is expected because the artifact is supplied through the agent container, and the verifier still received it.

## Deviations and notes

- Codex printed `Model metadata for qwen3.8:27b-mtp-q4_K_M not found` (fallback metadata). It is a benign warning and the run completed normally.
- Only condition A was run. The word2vec branch of the generic runner was not re-run in this job; it is kept identical in logic to `run_codex_ollama_word2vec_trial.sh`.
- No existing file was edited. The raw run folder is excluded through `.git/info/exclude` instead of `.gitignore`.
- Grade strictness: Harbor's reward is binary (1 only if all cases pass). 23/37 passes is a valid failed attempt, not infra failure.
