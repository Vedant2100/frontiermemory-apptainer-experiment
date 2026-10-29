#!/usr/bin/env python3
"""Helpers for scripts/run_codex_ollama_word2vec_trial.sh (Codex CLI, local Ollama, Word2Vec task).

Writes counts, names, and status only. It never copies prompts, model output, memory text,
request bodies, or workspace contents into records.

Subcommands:
  seed-memory   mirror frontier_memory.agents.codex.MemoryCodex.run: check the memory folder, copy
                every file to $CODEX_HOME/memories/, and copy MEMORY.md to memory_summary.md when no
                memory_summary.md exists. Verify the official folder digest.
  probe-check   pass/fail for a one-turn Codex probe against Ollama (exit code, turns, POST status)
  ollama-audit  sanitized audit of the Ollama request bodies and GIN lines written during one trial
  run-meta      write run-meta.json in the shape trial-record expects
  augment       add provider, base_url host, Ollama audit, and context fields to trial-record.json
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "frontiermemory" / "src"))
# frontier_memory.memory is stdlib-only; importing it does not import Harbor.
from frontier_memory.memory import ENTRY_FILE, check_memory, memory_digest  # noqa: E402

CODEX_ENTRY_FILE = "memory_summary.md"  # same constant as frontier_memory/agents/codex.py
GIN_RE = re.compile(r'\[GIN\].*?\|\s*(\d{3})\s*\|.*?\|\s*(\w+)\s+"([^"]+)"')
AUDIT_SCHEMA = "word2vec-codex-ollama-audit/1"


def write_json(path: str | None, obj: dict) -> None:
    text = json.dumps(obj, indent=2) + "\n"
    if path:
        Path(path).write_text(text, encoding="utf-8")
    else:
        sys.stdout.write(text)


def read_json(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


# ------------------------------------------------------------------ seed-memory
def cmd_seed_memory(args: argparse.Namespace) -> int:
    root = Path(args.memory_dir).expanduser().resolve()
    report = check_memory(root)
    if not report["ok"]:
        raise SystemExit(f"invalid memory {root}: {report['errors']}")
    files = [entry["path"] for entry in report["files"]]
    digest = report["memory_sha256"]
    if args.expected_digest and digest != args.expected_digest:
        raise SystemExit(f"memory digest {digest} does not match the expected digest")
    # Recompute the official digest independently from the bytes on disk (same function as check_memory).
    if memory_digest(root, files) != digest:
        raise SystemExit("memory digest recomputation mismatch")

    remote_root = Path(args.codex_home) / "memories"  # CODEX_HOME/memories, as in codex.py
    uploads = [(rel, rel) for rel in files]
    if CODEX_ENTRY_FILE not in files:
        uploads.append((ENTRY_FILE, CODEX_ENTRY_FILE))
    for source, target in uploads:
        dest = remote_root / target
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes((root / source).read_bytes())
        os.chmod(dest, 0o600)
    write_json(args.output, {
        "memory_sha256": digest,
        "total_bytes": report["total_bytes"],
        "files": files,
        "seeded_as": sorted(target for _, target in uploads),
        "entry_copied_as_summary": CODEX_ENTRY_FILE not in files,
        "codex_home_relative": "memories",
    })
    return 0


# ------------------------------------------------------------------- probe-check
def gin_lines_after(server_log: Path, offset: int) -> list[tuple[str, str, str]]:
    try:
        lines = server_log.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return []
    found = []
    for line in lines[offset:]:
        match = GIN_RE.search(line)
        if match:
            found.append((match.group(1), match.group(2), match.group(3)))
    return found


def cmd_probe_check(args: argparse.Namespace) -> int:
    events = read_json(Path(args.summary)) if args.summary else {}
    gins = gin_lines_after(Path(args.server_log), args.gin_offset)
    responses_ok = [g for g in gins if g[2].endswith(args.endpoint) and g[0] == "200"]
    responses_all = [g for g in gins if g[2].endswith(args.endpoint)]
    ok = (
        args.codex_rc == 0
        and len(responses_ok) >= 1
        and int(events.get("turns_completed") or 0) >= 1
    )
    write_json(args.output, {
        "variant": args.variant,
        "codex_exit_code": args.codex_rc,
        "ollama_endpoint": args.endpoint,
        "ollama_requests_to_endpoint": len(responses_all),
        "ollama_requests_200": len(responses_ok),
        "turns_completed": events.get("turns_completed"),
        "pass": ok,
    })
    return 0 if ok else 1


# ------------------------------------------------------------------ ollama-audit
def scalar(value):
    return value if isinstance(value, (int, float, str, bool)) or value is None else type(value).__name__


def body_summary(body: dict) -> dict:
    """Setting-level summary of one request body. Message, instruction, and input text are never copied."""
    reasoning = body.get("reasoning")
    options = body.get("options") if isinstance(body.get("options"), dict) else {}
    tools = body.get("tools")
    return {
        "model": scalar(body.get("model")),
        "stream": scalar(body.get("stream")),
        "reasoning_present": isinstance(reasoning, dict),
        "reasoning_effort": scalar(reasoning.get("effort")) if isinstance(reasoning, dict) else None,
        "reasoning_summary": scalar(reasoning.get("summary")) if isinstance(reasoning, dict) else None,
        "reasoning_effort_top_level": scalar(body.get("reasoning_effort")),
        "think": scalar(body.get("think")),
        "temperature": scalar(body.get("temperature", options.get("temperature"))),
        "num_ctx": scalar(options.get("num_ctx")),
        "max_output_tokens": scalar(body.get("max_output_tokens", body.get("max_tokens"))),
        "tool_count": len(tools) if isinstance(tools, list) else None,
    }


def cmd_ollama_audit(args: argparse.Namespace) -> int:
    body_dir = Path(args.body_dir)
    before = set()
    if args.before_list and Path(args.before_list).is_file():
        before = set(Path(args.before_list).read_text(encoding="utf-8").split())
    bodies = sorted(p for p in body_dir.rglob("*_body.json") if p.name not in before) if body_dir.is_dir() else []
    per_endpoint: dict[str, int] = {}
    summaries = []
    for path in bodies:
        endpoint = re.sub(r"^\d{8}T\d{6}\.\d+Z-\d+_", "", path.name)
        endpoint = re.sub(r"_body\.json$", "", endpoint)
        per_endpoint[endpoint] = per_endpoint.get(endpoint, 0) + 1
        try:
            body = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            summaries.append({"endpoint": endpoint, "parse_error": True})
            continue
        if isinstance(body, dict):
            summaries.append({"endpoint": endpoint, **body_summary(body)})

    responses = [s for s in summaries if s.get("endpoint") == "v1_responses"]
    effort_values: dict[str, int] = {}
    for s in responses:
        key = str(s.get("reasoning_effort"))
        effort_values[key] = effort_values.get(key, 0) + 1
    gins = gin_lines_after(Path(args.server_log), args.gin_offset)
    gin_counts: dict[str, int] = {}
    for status, method, path in gins:
        k = f"{status} {method} {path}"
        gin_counts[k] = gin_counts.get(k, 0) + 1

    effort_reached = bool(responses) and all(s.get("reasoning_effort") == args.effort for s in responses)
    write_json(args.output, {
        "schema": AUDIT_SCHEMA,
        "expected_model": args.model,
        "expected_reasoning_effort": args.effort,
        "request_bodies_in_trial": len(bodies),
        "request_bodies_by_endpoint": per_endpoint,
        "responses_bodies": len(responses),
        "responses_reasoning_effort_values": effort_values,
        "responses_models": sorted({str(s.get("model")) for s in responses}),
        "responses_num_ctx_values": sorted({str(s.get("num_ctx")) for s in responses}),
        "responses_think_values": sorted({str(s.get("think")) for s in responses}),
        "responses_temperature_values": sorted({str(s.get("temperature")) for s in responses}),
        "effort_reached_every_responses_call": effort_reached,
        "ollama_gin_lines_in_trial": gin_counts,
        "body_sample_settings": responses[:1],
    })
    return 0


# ---------------------------------------------------------------------- run-meta
def cmd_run_meta(args: argparse.Namespace) -> int:
    out: dict = {}
    for item in args.pairs:
        key, value = item.split("=", 1)
        if value.isdigit():
            value = int(value)
        elif value in ("true", "false"):
            value = value == "true"
        out[key] = value
    write_json(args.output, out)
    return 0


# ----------------------------------------------------------------------- augment
def cmd_augment(args: argparse.Namespace) -> int:
    path = Path(args.trial_record)
    record = read_json(path)
    audit = read_json(Path(args.audit))
    ctx_before = read_json(Path(args.ps_before))
    ctx_after = read_json(Path(args.ps_after))
    record.update({
        "schema": "word2vec-codex-ollama-trial-record/1",
        "provider": args.provider,
        "provider_variant": args.variant,
        "provider_base_url_host": args.base_url_host,
        "codex_model_provider_source": "config.toml" if args.variant == "responses-custom-provider" else "--oss",
        "auth_file_present": False,
        "openai_credentials_mounted": False,
        "ollama_model": args.model,
        "ollama_num_ctx_loaded_before": _ctx(ctx_before, args.model),
        "ollama_num_ctx_loaded_after": _ctx(ctx_after, args.model),
        "ollama_effort_audit": audit,
        "temperature_setting": "not settable in Codex 0.157 (no config key); Ollama default used",
        "memory_mode": args.memory_mode,
    })
    path.write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({k: record.get(k) for k in ("trial_index", "condition", "valid", "failure_category",
                                                  "strict_reward", "cases_passed_of_6", "provider_variant")}))
    return 0


def _ctx(ps: dict, model: str):
    for m in ps.get("models") or []:
        if m.get("name") == model or m.get("model") == model:
            return m.get("context_length")
    return None


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("seed-memory")
    p.add_argument("--memory-dir", required=True)
    p.add_argument("--codex-home", required=True)
    p.add_argument("--expected-digest", default="")
    p.add_argument("--output")
    p.set_defaults(func=cmd_seed_memory)

    p = sub.add_parser("probe-check")
    p.add_argument("--summary", required=True)
    p.add_argument("--server-log", required=True)
    p.add_argument("--gin-offset", type=int, required=True)
    p.add_argument("--endpoint", default="/v1/responses")
    p.add_argument("--codex-rc", type=int, required=True)
    p.add_argument("--variant", required=True)
    p.add_argument("--output", required=True)
    p.set_defaults(func=cmd_probe_check)

    p = sub.add_parser("ollama-audit")
    p.add_argument("--body-dir", required=True)
    p.add_argument("--before-list")
    p.add_argument("--server-log", required=True)
    p.add_argument("--gin-offset", type=int, required=True)
    p.add_argument("--model", required=True)
    p.add_argument("--effort", required=True)
    p.add_argument("--output")
    p.set_defaults(func=cmd_ollama_audit)

    p = sub.add_parser("run-meta")
    p.add_argument("--output", required=True)
    p.add_argument("pairs", nargs="*")
    p.set_defaults(func=cmd_run_meta)

    p = sub.add_parser("augment")
    p.add_argument("--trial-record", required=True)
    p.add_argument("--audit", required=True)
    p.add_argument("--ps-before", required=True)
    p.add_argument("--ps-after", required=True)
    p.add_argument("--provider", required=True)
    p.add_argument("--variant", required=True)
    p.add_argument("--base-url-host", required=True)
    p.add_argument("--model", required=True)
    p.add_argument("--memory-mode", required=True)
    p.set_defaults(func=cmd_augment)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
