# Codex CLI + local Ollama harness smoke (Slurm job 302374)

Date: 2026-10-28. One no-memory trial on `build-word2vec-pipeline`. No OpenAI or ChatGPT credentials were used.

| Item | Value |
|---|---|
| Harness | Codex CLI 0.157.0-alpha.11.1, inside the task agent container (`--containall`, no host home, no auth.json) |
| Provider | custom `model_providers` entry, Responses API, `http://127.0.0.1:<per-job port>/v1` (Codex 0.157 rejects `wire_api = "chat"`) |
| Model | `qwen3.8:27b-mtp-q4_K_M`, Ollama 0.40.11, 65,536 context loaded before and after |
| Reasoning effort | `medium`, observed in 13 of 13 `/v1/responses` request bodies (`reasoning.effort`) |
| Temperature | Not settable in Codex; Ollama default applies (deviation from the 0.1 used elsewhere) |
| Memory mechanism | Mirrors official `frontier_memory/agents/codex.py`: memory folder copied to `$CODEX_HOME/memories/`, `features.memories=true` in both arms, `--ephemeral`, web search disabled |
| Grading | Unchanged verifier through Harbor `nop` with the exec-timeout wrapper (oracle-validated path) |

Trial result (condition A):
- Codex exited 0 after 227 s, 1 turn, 10 commands.
- Input 149,487 tokens (146,483 cached), output 9,586.
- `solution.py` present.
- Verifier collected 0 cases. The agent's module raised a missing-NLTK-resource `RuntimeError` at import. Strict 0, category COLLECTION_ERROR_OTHER (agent-caused; the oracle passes in the same verifier image).

Harness fix before this run: the runner's model-manifest existence check used `test -d` on a manifest that is a file. The first submission (job 302137) exited after 2 s for that reason.
