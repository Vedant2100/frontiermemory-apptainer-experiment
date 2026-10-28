# Word2Vec memory A/B, Codex CLI harness (Slurm job 302067)

Date: 2026-10-28. Exploratory; n=3 per arm, one task, one model. No causal or leaderboard claim.
Companion to `ab-v2-results.md` (OpenHands/Qwen arm). Not part of the Ollama/OpenHands protocol gates.

## Setup

| Item | Value |
|---|---|
| Task | `letta-ai/build-word2vec-pipeline`, original task instruction, unchanged verifier |
| Harness | Codex CLI `codex-cli 0.157.0-alpha.11.1`, `codex exec --json --ephemeral` |
| Model / reasoning | `gpt-reserve`, reasoning effort medium |
| Container isolation | Codex runs inside the task agent SIF (Apptainer, `--containall --cleanenv --no-home`), workspace bound at `/workspace`, private CODEX_HOME bound at `/codex-home`; host `/home/csgrad` not visible (preflight) |
| Memory (B only) | Frozen v2 memory, sha256 `eb044c32…`, delivered as Codex's global `$CODEX_HOME/AGENTS.md` (A has no AGENTS.md) |
| Prompt | Shared base template (sha256 `61ba8b92…`, rendered with `instruction.md`), identical in all 6 trials |
| Limits | Agent timeout 1200 s (no trial timed out); sequential trials, fresh workspace and fresh CODEX_HOME each |
| Grading | Unchanged verifier, copy of workspace graded via Harbor `nop` agent (wrapped exec path) |
| Reference | Oracle 6/6 on this pipeline (earlier oracle checks, jobs 301906 and 301915) |
| Egress | Verifier egress not isolated (public network mode). Codex web search not explicitly disabled (see limitations) |
| Data sent to OpenAI | Task instruction and, in B, the frozen memory text |

## Per-trial results

| # | Arm | Category | Strict reward | Cases passed / 6 | Agent s | Commands | File-change entries | Input tok (cached) | Output tok | Reasoning tok |
|---|---|---|---|---|---|---|---|---|---|---|
| 1 | A | contract collection error | 0 | 0 | 39 | 8 | 2 | 139,282 (122,368) | 4,077 | 1,298 |
| 2 | B | tests failed | 0 | 1 | 27 | 3 | 1 | 61,366 (46,848) | 2,776 | 1,038 |
| 3 | B | tests failed | 0 | 1 | 35 | 6 | 3 | 106,235 (89,344) | 3,247 | 1,006 |
| 4 | A | contract collection error | 0 | 0 | 37 | 5 | 1 | 87,493 (56,448) | 3,879 | 1,341 |
| 5 | A | contract collection error | 0 | 0 | 40 | 5 | 2 | 100,209 (83,072) | 4,033 | 1,358 |
| 6 | B | tests failed | 0 | 1 | 30 | 4 | 1 | 75,339 (60,416) | 2,728 | 807 |

All six trials are valid under decision D5' (solution artifact present, verifier executed, no infrastructure fault, no Harbor exception). Each trial was one Codex turn (`turns_started` = 1). Codex exit 0 in all six; Harbor grading exit 0 in all six.

## Per-arm summary

| Arm | Strict passes | Tests collected | Mean cases / 6 | Mean agent time | Mean input tok (cached) | Mean output tok | Mean reasoning tok |
|---|---|---|---|---|---|---|---|
| A (no memory) | 0/3 | 0/3 | 0.0 | 38.7 s | 108,995 (87,296) | 3,996 | 1,332 |
| B (frozen memory as AGENTS.md) | 0/3 | 3/3 | 1.0 | 30.7 s | 80,980 (65,536) | 2,917 | 950 |

Smoke trial (job 302065, condition A, separate row, not counted in the arms above): strict 0, cases 0/6, `CONTRACT_COLLECTION_ERROR`, agent 41 s, 4 commands, 2 file-change entries, input 84,682 (cached 70,016), output 3,192, reasoning 796.

## Comparison with the OpenHands/Qwen A/B (job 301916)

Same qualitative pattern. Strict passes were 0/3 in both arms. Collection was 0/3 for A and 3/3 for B, with 1/6 cases passed in each B trial. The Codex runs finished in one turn each (about 27 to 40 s agent time). The OpenHands runs took 12 to 51 requests and 230 to 771 s. That difference is about the harness and model turn structure, not a like-for-like speed comparison.

## Consistency checks

- Prompt sha256: `61ba8b92…` in all six trials.
- Memory sha256: `eb044c32…` in the three B trials; no AGENTS.md in the three A trials.
- Model `gpt-reserve`, reasoning medium, Codex `codex-cli 0.157.0-alpha.11.1` in all six trials.
- Web search or MCP events: 0. Event item types were only `command_execution`, `file_change`, and `agent_message`.
- Auth refreshed / copied back: no / no in all six trials.
- Codex stderr: only the `HOME` override warning from Apptainer (6 lines, one per trial).
- No trial timed out; all Codex exits 0.

## Limitations

- n=3 per arm, one task, one model, one job. Results are descriptive and not statistically powered.
- Memory was family-selected for this task (frozen v2 memory), so B is not a neutral memory condition.
- Memory placement differs from the OpenHands arm. Here it is Codex's global `AGENTS.md`; there it was appended to the prompt.
- Verifier egress is not isolated (public network mode), as in the protocol.
- Codex web search was not explicitly disabled. The `web_search_mode` key is ignored by this Codex build, so the default applies. No web events were observed in any trial, but the default is not verified.
- The task instruction and, in B, the memory text were sent to OpenAI.
- Prompt rendering used a single-placeholder substitution, not Jinja, so whitespace may differ from the OpenHands request bytes.
- Raw event streams, stderr, workspaces, and Harbor trial directories stay local and git-ignored under `results/word2vec-openhands/codex-v2/job-302067/`.
