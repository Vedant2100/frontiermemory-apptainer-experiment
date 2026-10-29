"""Evidence judge over a local Ollama server (preregistration v1, section 2.4).

Temperature 0, fixed seed, JSON output checked against a schema. A reply that is not valid JSON
or has an unknown verdict is retried, up to MAX_ATTEMPTS in total. On retries a short
reminder is appended to the prompt. If every attempt fails, the verdict is 'insufficient' and
the unit is flagged (bad_json=True), and the flag is counted. Transport errors (server down,
timeouts) are not judged. They are retried with backoff and then raised, so the run stops.
"""

from __future__ import annotations

import hashlib
import json
import re
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path

from evidence import Excerpt

VERDICTS = ("supported", "contradicted", "insufficient")
MAX_ATTEMPTS = 3
TRANSPORT_ATTEMPTS = 4
PROMPT_PATH = Path(__file__).with_name("judge_prompt.md")
RETRY_NOTE = (
    "\n\nYour previous reply was not valid JSON with one of the allowed verdicts. "
    "Reply with only the JSON object."
)
THINK_BLOCK = re.compile(r"<think>.*?</think>", re.DOTALL | re.IGNORECASE)
SCHEMA = {
    "type": "object",
    "properties": {
        "quote": {"type": "string"},
        "verdict": {"type": "string", "enum": list(VERDICTS)},
        "reason": {"type": "string"},
    },
    "required": ["quote", "verdict", "reason"],
}


class JudgeTransportError(RuntimeError):
    """The Ollama server could not be reached or did not answer. The run must stop."""


@dataclass
class JudgeResult:
    verdict: str
    attempts: int
    bad_json: bool
    reason: str  # kept in memory only; never written to logs
    quote: str  # kept in memory only; never written to logs


def prompt_template() -> tuple[str, str]:
    raw = PROMPT_PATH.read_bytes()
    return raw.decode("utf-8"), hashlib.sha256(raw).hexdigest()


def render_evidence(excerpts: list[Excerpt]) -> str:
    if not excerpts:
        return "(no excerpts available)"
    blocks = []
    for n, ex in enumerate(excerpts, start=1):
        note = " [excerpt truncated]" if ex.truncated else ""
        blocks.append(
            f"--- Excerpt {n} (run outcome: {ex.outcome}; step {ex.step}; role: {ex.role}){note}\n"
            f"{ex.text}"
        )
    return "\n\n".join(blocks)


def render_prompt(template: str, claim: str, excerpts: list[Excerpt]) -> str:
    return template.replace("{{CLAIM}}", claim).replace("{{EVIDENCE}}", render_evidence(excerpts))


def parse_reply(content: str) -> tuple[str, str, str] | None:
    """Return (verdict, reason, quote), or None when the reply is not a valid judgement."""
    try:
        obj = json.loads(THINK_BLOCK.sub("", content).strip())
    except (json.JSONDecodeError, TypeError):
        return None
    if not isinstance(obj, dict):
        return None
    verdict = obj.get("verdict")
    reason = obj.get("reason", "")
    quote = obj.get("quote")
    if verdict not in VERDICTS or not isinstance(reason, str) or not isinstance(quote, str):
        return None
    return verdict, reason, quote


class OllamaJudge:
    def __init__(self, url: str, model: str, *, seed: int = 2027, num_ctx: int = 16384,
                 timeout: float = 900.0):
        self.url = url
        self.model = model
        self.seed = seed
        self.num_ctx = num_ctx
        self.timeout = timeout

    def _chat(self, prompt: str) -> str:
        body = {
            "model": self.model,
            "stream": False,
            "messages": [{"role": "user", "content": prompt}],
            "format": SCHEMA,
            "think": False,
            "options": {
                "temperature": 0,
                "seed": self.seed,
                "num_ctx": self.num_ctx,
                "num_predict": 320,
            },
        }
        request = urllib.request.Request(
            self.url,
            data=json.dumps(body).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        last_error: Exception | None = None
        for attempt in range(TRANSPORT_ATTEMPTS):
            try:
                with urllib.request.urlopen(request, timeout=self.timeout) as response:
                    payload = json.loads(response.read().decode("utf-8"))
                return payload["message"]["content"]
            except (urllib.error.URLError, TimeoutError, ConnectionError, KeyError, ValueError) as error:
                last_error = error
                time.sleep(5 * (attempt + 1))
        raise JudgeTransportError(f"Ollama request failed after {TRANSPORT_ATTEMPTS} tries: {last_error!r}")

    def judge(self, template: str, claim: str, excerpts: list[Excerpt]) -> JudgeResult:
        prompt = render_prompt(template, claim, excerpts)
        for attempt in range(1, MAX_ATTEMPTS + 1):
            text = prompt if attempt == 1 else prompt + RETRY_NOTE
            parsed = parse_reply(self._chat(text))
            if parsed is not None:
                verdict, reason, quote = parsed
                return JudgeResult(verdict=verdict, attempts=attempt, bad_json=False,
                                   reason=reason, quote=quote)
        return JudgeResult(verdict="insufficient", attempts=MAX_ATTEMPTS, bad_json=True,
                           reason="", quote="")
