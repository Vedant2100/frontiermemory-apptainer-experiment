#!/usr/bin/env python3
"""Record Ollama's model-specific thinking controls and verify both APIs."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


def post(url: str, payload: dict) -> dict:
    request = Request(
        url,
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urlopen(request, timeout=300) as response:
            return json.load(response)
    except (HTTPError, URLError) as error:
        body = error.read().decode(errors="replace") if isinstance(error, HTTPError) else str(error)
        return {"probe_error": body}


def save(path: Path, payload: dict) -> None:
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def summarize_native(response: dict) -> dict:
    message = response.get("message", {})
    return {
        "error": response.get("probe_error"),
        "thinking_chars": len(message.get("thinking", "")),
        "content_chars": len(message.get("content", "")),
        "prompt_eval_count": response.get("prompt_eval_count"),
        "eval_count": response.get("eval_count"),
        "done_reason": response.get("done_reason"),
    }


def summarize_openai(response: dict) -> dict:
    choices = response.get("choices", [])
    message = choices[0].get("message", {}) if choices else {}
    usage = response.get("usage", {})
    return {
        "error": response.get("probe_error") or response.get("error"),
        "reasoning_chars": len(
            message.get("reasoning_content", "") or message.get("reasoning", "")
        ),
        "content_chars": len(message.get("content", "") or ""),
        "prompt_tokens": usage.get("prompt_tokens"),
        "completion_tokens": usage.get("completion_tokens"),
        "finish_reason": choices[0].get("finish_reason") if choices else None,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default="http://127.0.0.1:11434")
    parser.add_argument("--model", required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)
    base = args.base_url.rstrip("/")
    show = post(f"{base}/api/show", {"model": args.model})
    save(args.output_dir / "model-show.json", show)

    prompt = "Think privately if needed. Answer only with the integer result of 17 * 19."
    native = post(
        f"{base}/api/chat",
        {
            "model": args.model,
            "messages": [{"role": "user", "content": prompt}],
            "think": False,
            "stream": False,
            "options": {"num_predict": 128},
        },
    )
    save(args.output_dir / "native-think-false.json", native)
    native_default = post(
        f"{base}/api/chat",
        {
            "model": args.model,
            "messages": [{"role": "user", "content": prompt}],
            "stream": False,
            "options": {"num_predict": 128},
        },
    )
    save(args.output_dir / "native-default-thinking.json", native_default)
    openai = post(
        f"{base}/v1/chat/completions",
        {
            "model": args.model,
            "messages": [{"role": "user", "content": prompt}],
            "reasoning_effort": "none",
            "stream": False,
            "max_tokens": 128,
        },
    )
    save(args.output_dir / "openai-reasoning-none.json", openai)
    summary = {
        "model": args.model,
        "thinking_controls": show.get("thinking"),
        "native_think_false": summarize_native(native),
        "native_default": summarize_native(native_default),
        "openai_reasoning_none": summarize_openai(openai),
    }
    save(args.output_dir / "thinking-probe-summary.json", summary)
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
