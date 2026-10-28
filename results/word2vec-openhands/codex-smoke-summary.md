# Word2Vec Codex CLI smoke trial (Slurm job 302065)

Date: 2026-10-28. Companion harness to `protocol-v2.md`, not one of its Ollama/OpenHands gates.
One no-memory trial (condition A). Model `gpt-reserve`, reasoning effort `medium`. Codex CLI
`codex-cli 0.157.0-alpha.11.1`. CPU-only `batch` partition, 4 CPUs, 8 GB, time limit 1 h.

Slurm: `COMPLETED`, exit `0:0`, elapsed `00:01:36`. No resubmission. The job was run once.

## Preflight (inside the task agent container)

| Check | Result |
|---|---|
| Host `/home/csgrad` visible in container | no |
| Container `/home` listing | image-internal only |
| `/workspace` empty at start | yes (0 entries) |
| `node` inside container | v22.23.3 |
| `codex --version` inside container | ok (`codex-cli 0.157.0-alpha.11.1`) |
| Disabled features read back as disabled (memories, plugins, apps, browser use, multi-agent, computer use, remote plugin, plugin sharing, in-app browser) | yes |
| `api.openai.com` reachable from container | yes (HTTP 401 without credentials, so reachable) |
| Verifier image test-file hashes match pinned source | yes |

## Trial record (sanitized counts)

| Field | Value |
|---|---|
| Condition | A (no memory, no AGENTS.md) |
| Strict reward | 0 |
| Cases passed | 0 of 6 |
| Failure category | `CONTRACT_COLLECTION_ERROR` (valid FAIL) |
| `/workspace/solution.py` produced | yes (Harbor artifact status `ok`) |
| Verifier collected cases | 0 (one collection error, with missing-attribute errors) |
| Codex exit code | 0 |
| Timed out (1200 s) | no |
| Agent wall time | 41 s |
| Model turns | 1 |
| Commands executed | 4 |
| File-change entries | 2 |
| Input tokens | 84,682 |
| Cached input tokens | 70,016 |
| Output tokens | 3,192 |
| Reasoning output tokens | 796 |
| Prompt sha256 | `61ba8b92...` (shared base template with `instruction.md` substituted) |
| Memory sha256 | not applicable (A) |
| Auth refreshed / copied back | no / no |
| Verifier network mode | public (egress isolation not enforced, as in the protocol) |

Protocol gate status: the smoke trial did not meet the Phase 3 gate. The solution file was
created, but the verifier collected 0 cases, below the required minimum of 1. The trial is still
a valid, scored FAIL under decision D5'. It is not a retry.

## Deviations and uncertainties

- **Web search not disabled.** The key `web_search_mode` is reported as an ignored setting by this
  Codex build (warning in the event stream). It was removed from the runner, so web search follows
  Codex's default for this build. No web-search events occurred in this trial. That default is not
  verified. Conditions A and B will share the same default, so the comparison is unaffected, but the
  trial is not offline in the strict sense.
- **Config validation limit.** This build has no no-model subcommand that validates config keys. A
  validation probe would need a model call, so none was made.
- **Prompt rendering.** The shared template was rendered by substituting the single
  `{{ instruction }}` placeholder, not by Jinja. Whitespace may differ from the OpenHands request bytes.
- **Memory placement (for B, not run here).** The frozen memory is delivered as Codex's global
  `AGENTS.md`. The OpenHands arm appended it to the prompt, so the two arms differ in placement.
- **Codex runtime quirks.** Codex's `HOME` override is rejected by Apptainer (warning only), and the
  container image's `/home` lists a non-host entry. Neither affected the isolation check.
- **Raw outputs.** Event stream, stderr, workspace, and Harbor trial directories stay local and
  git-ignored under `results/word2vec-openhands/codex-v2/job-302065/`. The event stream contains
  model output, so it is not published.
- **Record derivation.** The trial record was regenerated once after the record helper gained the
  `COLLECTION_ERROR_OTHER` split. The earlier record is kept as `trial-record-pre-category-split.json`.
  Its category was unchanged.
