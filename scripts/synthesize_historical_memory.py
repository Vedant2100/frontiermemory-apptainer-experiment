#!/usr/bin/env python3
"""Synthesize a concise memory from historical corpus evidence via local Ollama."""

from __future__ import annotations

import argparse
import json
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.request import Request, urlopen


SYSTEM_PROMPT = """You turn evidence-backed lessons from historical coding-agent trajectories into concise reusable memory for a future coding agent.

Use only the historical evidence supplied in the user message. Keep rules actionable and general; do not carry over task-specific APIs, algorithms, or requirements from a source task. Do not invent facts, hidden answers, verifier details, or causal claims. Do not mention any evaluation target or experiment/debugging history. Return at most four short Markdown bullets. Each bullet must include situation, learned rule, and evidence. Every evidence field must cite one or more exact references in the form `inputs/tNNNN.json#step=N`, using only references present in the supplied evidence. If evidence does not support a rule, omit it."""


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--evidence", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--metrics", type=Path, required=True)
    parser.add_argument("--request-record", type=Path, required=True)
    parser.add_argument("--model", default="qwen3-coder:30b")
    parser.add_argument("--api", default="http://127.0.0.1:11434/api/chat")
    parser.add_argument("--context", type=int, default=65536)
    args = parser.parse_args()

    historical_evidence = args.evidence.read_text(encoding="utf-8")
    if not historical_evidence.strip():
        raise ValueError("Historical evidence input is empty")
    request_body = {
        "model": args.model,
        "stream": False,
        "keep_alive": "20m",
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": historical_evidence},
        ],
        "options": {"temperature": 0, "num_ctx": args.context, "num_predict": 2400},
    }
    args.request_record.parent.mkdir(parents=True, exist_ok=True)
    args.request_record.write_text(json.dumps(request_body, indent=2) + "\n", encoding="utf-8")

    started = time.monotonic()
    request = Request(
        args.api,
        data=json.dumps(request_body).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urlopen(request, timeout=1800) as response:
        response_body = json.load(response)
    elapsed = time.monotonic() - started

    content = (response_body.get("message") or {}).get("content", "").strip()
    if len(content) < 300:
        raise ValueError("Local model returned an empty or implausibly short memory")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(content + "\n", encoding="utf-8")
    metrics = {
        "model": args.model,
        "api": args.api,
        "context_requested": args.context,
        "source": str(args.evidence),
        "source_bytes": args.evidence.stat().st_size,
        "memory_bytes": len(content.encode("utf-8")),
        "prompt_tokens": response_body.get("prompt_eval_count"),
        "completion_tokens": response_body.get("eval_count"),
        "ollama_total_duration_ns": response_body.get("total_duration"),
        "wall_seconds": round(elapsed, 3),
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }
    args.metrics.write_text(json.dumps(metrics, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(metrics, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
