#!/usr/bin/env python3
"""Task-specific helpers for scripts/run_codex_ollama_trial.sh (Codex CLI, local Ollama).

Generic over TASK (build-word2vec-pipeline or dapt-intrusion-detection-workflow-learning). Shared
pieces are reused from the word2vec harness and not duplicated here:
  scripts/word2vec_ab_v2_records.py   verifier parsing, failure categories (D5')
  scripts/word2vec_codex_trial.py     summarize-events, aggregate
  scripts/word2vec_codex_ollama_helper.py  seed-memory, probe-check, ollama-audit, run-meta

Writes counts, names, and hashes only. It never copies prompts, model output, memory text,
request bodies, or workspace contents into records.

Subcommands:
  task-meta      read the staged task.toml, check artifact paths, write task metadata JSON
  render-prompt  shared "Required output artifacts" header built from task metadata + instruction.md
  manifest       sha256 list (sha256sum format, sorted) of every regular file under a directory
  trial-record   one sanitized trial-record.json; cases_total is task-specific (6 or 37)
  verify-memory  check one memory folder against its expected official digest (counts and digest only)
  balanced-order print the preregistered balanced TRIAL_ORDER (Latin rotation over the arms, 3 rounds)
  aggregate      trials-summary.json for one job: trial records plus per-arm groups
  add-verifier-env  add the task's spec verifier_env entries to a staged task.toml (grading copy only)
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import tomllib
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from word2vec_ab_v2_records import categorize, parse_verifier, read_json  # noqa: E402

SCHEMA = "codex-ollama-trial-record/1"
USAGE_KEYS = ("input_tokens", "cached_input_tokens", "output_tokens", "reasoning_output_tokens")
TASK_SPECS = {
    # cases_total: verifier cases in the task (word2vec: 6; DAPT: 37, oracle 37/37 in the DAPT oracle check).
    # artifact_mode "file" (default): the agent writes the declared file under workdir.
    # artifact_mode "patch": the agent edits the repository in workdir; the task's [[verifier.collect]]
    #   command writes the declared patch. The verifier reports f2p/p2p totals in reward.json, and
    #   cases_total is their sum (cattrs: 70 + 7, matched by the oracle check).
    "build-word2vec-pipeline": {"cases_total": 6, "workdir": "/workspace"},
    "dapt-intrusion-detection-workflow-learning": {"cases_total": 37, "workdir": "/root"},
    # awilix (release-tier implicit and explicit): official test.sh runs Jest twice (base = regression, then new =
    #   functional) and prints "Tests: ..." summary lines between "--- Step 3" and "--- Step 4" markers. Cases are
    #   passed + failed per section; skipped tests are not cases (1 functional skip, by design, in the oracle run).
    #   cases_total 184 = regression 161 + functional 23 (oracle run: 161/161 and 23/23 passing, 1 skipped).
    #   The declared artifact is /logs/artifacts (a directory); the collect step writes model.patch inside it.
    "awilix-release-tier-implicit": {"cases_total": 184, "workdir": "/app", "artifact_mode": "patch",
                                     "artifact_path": "/logs/artifacts", "artifact_is_dir": True,
                                     "verifier_format": "jest-sections"},
    "awilix-release-tier-explicit": {"cases_total": 184, "workdir": "/app", "artifact_mode": "patch",
                                     "artifact_path": "/logs/artifacts", "artifact_is_dir": True,
                                     "verifier_format": "jest-sections"},
    # customer-delivery: reward.json (grader.py) gives f2p (26) and p2p (162, incl. the "[gate] npm run build" id).
    #   cases_total = 188. The preference check reports a CTRF summary (user-preference-ctrf.json), recorded as counts.
    "customer-delivery-contextual-preferences": {"cases_total": 188, "workdir": "/app", "artifact_mode": "patch",
                                                 "artifact_path": "/logs/artifacts/model.patch",
                                                 "preference_format": "ctrf-summary"},
    "cattrs-compositional-changelog": {"cases_total": 77, "workdir": "/app", "artifact_mode": "patch",
                                       "artifact_path": "/logs/artifacts/model.patch"},
    # cookie-store: test.sh writes reward.txt (strict 0/1), functional-reward.txt, and two pytest summary lines in
    #   verifier/test-stdout.txt (regression first, then functional) plus [user-preference-gate] lines. cases_total
    #   is regression (1285 = passed + errors) + functional (115), as in the oracle check (303229: 1400).
    #   verifier_env is the [verifier.env] addition of the oracle check (safe.directory for git, USER/LOGNAME root).
    #   The verifier SIF is -v3 (agent uid-0 alias, see its def).
    "cookie-store-compositional-changelog": {
        "cases_total": 1400, "workdir": "/app", "artifact_mode": "patch",
        "artifact_path": "/logs/artifacts/model.patch", "verifier_format": "cookie-store-text",
        "verifier_env": {"GIT_CONFIG_COUNT": "1", "GIT_CONFIG_KEY_0": "safe.directory",
                         "GIT_CONFIG_VALUE_0": "*", "USER": "root", "LOGNAME": "root"},
    },
}
PATCH_HEADER_ARTIFACT_LINE = (
    "The official task metadata declares this file as a required output: `{path}`. It is produced by the task's "
    "collection step, not written by hand. After you finish, that step takes the diff of the repository in your "
    "working directory (`{workdir}`) against the task's base commit, as committed on HEAD.\n"
)
# Same text for a declared artifact path that is a directory (awilix: /logs/artifacts); cattrs/cookie keep the line above.
PATCH_HEADER_ARTIFACT_DIR_LINE = PATCH_HEADER_ARTIFACT_LINE.replace(
    "declares this file as a required output", "declares this artifact location as a required output")
ZERO_CASES_CATEGORIES = ("NO_ARTIFACT", "CONTRACT_COLLECTION_ERROR", "COLLECTION_ERROR_OTHER")
# Preregistration v1 section 3: 3 rounds of a Latin rotation over these five arms (A0 = no memory).
PREREG_ARMS = ("A0", "R25", "M3", "G", "GR")
PREREG_ROUNDS = 3


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read_text_or_empty(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""


def parse_reward_json(path: Path) -> dict:
    """Counts from a patch task's verifier/reward.json (written by the official test.sh).

    Format seen in prior cattrs runs: {"reward": 0|1, "f2p_total", "f2p_passed", "p2p_total", "p2p_passed",
    "f2p", "p2p", "partial"}. Functional-to-pass plus pass-to-pass give the per-case totals.
    """
    data = read_json(path) if path.is_file() else None
    if not isinstance(data, dict) or "reward" not in data:
        return {"output_present": False, "collected": 0, "passed": 0, "failed": 0, "errors": 0,
                "skipped": 0, "collection_error": False, "parse_note": "reward.json absent"}
    collected = int(data.get("f2p_total", 0)) + int(data.get("p2p_total", 0))
    passed = int(data.get("f2p_passed", 0)) + int(data.get("p2p_passed", 0))
    return {"output_present": True, "collected": collected, "passed": passed, "failed": collected - passed,
            "errors": 0, "skipped": 0, "collection_error": collected == 0, "parse_note": None}


# Cookie-store verifier output (see the TASK_SPECS comment). Summary lines: "N passed, M skipped in 12.3s".
COOKIE_SUMMARY_RE = re.compile(r"^=*\s*((?:\d+ [a-z]+,? ?)+) in [0-9.]+s")
COOKIE_COUNT_RE = re.compile(r"(\d+) ([a-z]+)")
COOKIE_GATE_RE = re.compile(r"^\[user-preference-gate\] (PASS|FAIL)\b", re.M)


def _pytest_run_counts(line_counts: dict) -> dict:
    return {"passed": line_counts.get("passed", 0), "failed": line_counts.get("failed", 0),
            "errors": line_counts.get("error", 0) + line_counts.get("errors", 0),
            "skipped": line_counts.get("skipped", 0)}


def parse_cookie_store(vdir: Path) -> dict:
    """Counts from a cookie-store verifier directory (written by the official test.sh).

    Regression = the first pytest summary line (base tests), functional = the second (new tests), as in the
    oracle check. Gate counts come from the [user-preference-gate] lines. Counts only; no test names.
    """
    text = read_text_or_empty(vdir / "test-stdout.txt")
    runs = []
    for line in text.splitlines():
        m = COOKIE_SUMMARY_RE.match(line.strip())
        if m:
            runs.append({word: int(n) for n, word in COOKIE_COUNT_RE.findall(m.group(1))})
    reg = _pytest_run_counts(runs[0]) if len(runs) > 0 else {"passed": 0, "failed": 0, "errors": 0, "skipped": 0}
    fun = _pytest_run_counts(runs[1]) if len(runs) > 1 else {"passed": 0, "failed": 0, "errors": 0, "skipped": 0}
    total = {k: reg[k] + fun[k] for k in reg}
    collected = total["passed"] + total["failed"] + total["errors"]
    notes = [] if len(runs) == 2 else [f"expected 2 pytest summary lines, found {len(runs)}"]
    gates = COOKIE_GATE_RE.findall(text)
    score = read_text_or_empty(vdir / "user-preference-score.txt").strip() or None
    functional_reward = read_text_or_empty(vdir / "functional-reward.txt").strip() or None
    return {
        "output_present": (vdir / "test-stdout.txt").is_file(),
        "collected": collected, "passed": total["passed"], "failed": total["failed"], "errors": total["errors"],
        "skipped": total["skipped"], "collection_error": collected == 0 and total["errors"] > 0,
        "parse_note": "; ".join(notes) or None,
        "regression": reg, "functional": fun,
        "regression_collected": reg["passed"] + reg["failed"] + reg["errors"],
        "functional_collected": fun["passed"] + fun["failed"] + fun["errors"],
        "functional_reward": functional_reward,
        "preference_gates_pass": gates.count("PASS"), "preference_gates_fail": gates.count("FAIL"),
        "preference_score": score,
        "user_preference_json_present": (vdir / "user-preference.json").is_file(),
    }


ANSI_ESCAPE = re.compile(r"\x1b\[[0-9;]*[A-Za-z]")
JEST_TESTS_LINE = re.compile(r"^\s*Tests:\s+(.*)$", re.M)
JEST_COUNT = re.compile(r"(\d+) (passed|failed|skipped|todo|pending|total)")
VERIFIER_RESULT_LINE = re.compile(r"^\[verifier\] functional=(\d+) preference=(\d+) strict=(\d+)\s*$", re.M)


def _jest_section(text: str) -> dict:
    """Last Jest "Tests:" summary line of one section: {summary_lines, passed, failed, skipped, total}."""
    lines = JEST_TESTS_LINE.findall(text)
    out = {"summary_lines": len(lines), "passed": 0, "failed": 0, "skipped": 0, "total": 0}
    if lines:
        for number, kind in JEST_COUNT.findall(lines[-1]):
            out["skipped" if kind in ("todo", "pending") else kind] += int(number)
    return out


def parse_jest_sections(vdir: Path) -> dict:
    """Counts from an awilix verifier directory (official test.sh, Jest). Counts only; no test names."""
    text = ANSI_ESCAPE.sub("", read_text_or_empty(vdir / "test-stdout.txt"))
    head, sep, tail = text.partition("--- Step 4: Running new tests ---")
    regression_text = head.partition("--- Step 3: Running baseline tests ---")[2] if sep else head
    reg = _jest_section(regression_text)
    fun = _jest_section(tail if sep else "")
    results = VERIFIER_RESULT_LINE.findall(text)
    preference = int(results[-1][1]) if results else None
    reg_cases = reg["passed"] + reg["failed"]
    fun_cases = fun["passed"] + fun["failed"]
    notes = [] if results else ["no [verifier] result line"]
    return {
        "output_present": (vdir / "test-stdout.txt").is_file(),
        "collected": reg_cases + fun_cases, "passed": reg["passed"] + fun["passed"],
        "failed": reg["failed"] + fun["failed"], "errors": 0,
        "skipped": reg["skipped"] + fun["skipped"],
        "collection_error": (reg_cases + fun_cases) == 0,
        "parse_note": "; ".join(notes) or None,
        "regression": reg, "functional": fun,
        "regression_collected": reg_cases, "functional_collected": fun_cases,
        "functional_reward": read_text_or_empty(vdir / "functional-reward.txt").strip() or None,
        "preference_pass": preference,
        "preference_json_present": (vdir / "user-preference-ctrf.json").is_file(),
    }


def parse_ctrf_preference(vdir: Path) -> dict:
    """Preference counts from the CTRF summary the preference verifier writes (user-preference-ctrf.json).

    Harbor's verifier dir may hold it directly or under reports/ (test.sh moves framework reports there).
    """
    for candidate in (vdir / "user-preference-ctrf.json", vdir / "reports" / "user-preference-ctrf.json"):
        data = read_json(candidate) if candidate.is_file() else None
        if isinstance(data, dict):
            summary = (data.get("results") or {}).get("summary") or {}
            return {"preference_present": True, "preference_passed": int(summary.get("passed", 0)),
                    "preference_total": int(summary.get("tests", 0))}
    return {"preference_present": False, "preference_passed": None, "preference_total": None}


def spec_for(task: str) -> dict:
    if task not in TASK_SPECS:
        raise SystemExit(f"unknown TASK {task!r}")
    return TASK_SPECS[task]


# ------------------------------------------------------------ add-verifier-env
def add_verifier_env_lines(text: str, env: dict) -> str:
    """Insert the [verifier.env] entries right after the single [verifier.env] header (same text as the oracle check)."""
    header = "[verifier.env]\n"
    if text.count(header) != 1:
        raise SystemExit("expected one [verifier.env] table")
    entries = "".join(f"{key} = {json.dumps(value)}\n" for key, value in env.items())
    return text.replace(header, header + entries, 1)


def cmd_add_verifier_env(args: argparse.Namespace) -> int:
    spec = spec_for(args.task)
    env = spec.get("verifier_env")
    if not env:
        print("no verifier_env for this task")
        return 0
    path = Path(args.task_toml)
    path.write_text(add_verifier_env_lines(path.read_text(encoding="utf-8"), env), encoding="utf-8")
    tomllib.loads(path.read_text(encoding="utf-8"))
    print(json.dumps({"verifier_env_keys": sorted(env)}))
    return 0


# -------------------------------------------------------------------- task-meta
def cmd_task_meta(args: argparse.Namespace) -> int:
    spec = spec_for(args.task)
    task = tomllib.loads(Path(args.task_toml).read_text(encoding="utf-8"))
    if task["task"]["name"] and args.task not in task["task"]["name"]:
        raise SystemExit(f"task.toml name {task['task']['name']!r} does not match TASK {args.task!r}")
    artifacts = task.get("artifacts", [])
    mode = spec.get("artifact_mode", "file")
    prefix = spec["workdir"] + "/"
    if mode == "patch":
        if artifacts != [spec["artifact_path"]]:
            raise SystemExit(f"Unexpected artifact metadata for patch task: {artifacts!r}")
        collects = task["verifier"].get("collect") or []
        if len(collects) != 1 or spec["artifact_path"] not in collects[0].get("command", ""):
            raise SystemExit("patch task needs one [[verifier.collect]] command that writes the declared artifact")
    elif not artifacts or any(not isinstance(p, str) or not p.startswith(prefix) for p in artifacts):
        raise SystemExit(f"Unexpected or missing artifact metadata: {artifacts!r}")
    if len(artifacts) != 1:
        raise SystemExit("this runner grades exactly one declared artifact")
    verifier = task["verifier"]["environment"]
    if verifier.get("network_mode") != "public":
        raise SystemExit("staged verifier network_mode must be public (Harbor Singularity rejects no-network)")
    out = {
        "task": args.task,
        "task_name": task["task"]["name"],
        "declared_artifacts": artifacts,
        "artifact_rel": [p[len(prefix):] if mode == "file" else p.lstrip("/") for p in artifacts],
        "workdir": spec["workdir"],
        "cases_total": spec["cases_total"],
        "agent_timeout_sec": task["agent"]["timeout_sec"],
        "verifier_timeout_sec": task["verifier"]["timeout_sec"],
        "verifier_network_mode_staged": verifier["network_mode"],
        "network_egress_isolation_enforced": False,
    }
    if mode == "patch":
        collect = task["verifier"]["collect"][0]
        out.update({
            "artifact_mode": "patch",
            "artifact_is_dir": bool(spec.get("artifact_is_dir", False)),
            "collect_command": collect["command"],
            "collect_timeout_sec": int(float(collect.get("timeout_sec", 60.0))),
        })
    Path(args.output).write_text(json.dumps(out, indent=2) + "\n", encoding="utf-8")
    return 0


# ----------------------------------------------------------------- render-prompt
def cmd_render_prompt(args: argparse.Namespace) -> int:
    meta = json.loads(Path(args.task_meta).read_text(encoding="utf-8"))
    if meta.get("artifact_mode") == "patch":
        # Patch task: the declared file is produced by the collection step (task.toml [[verifier.collect]]),
        # so the header states that contract instead of asking for files to be created at exact paths.
        line = PATCH_HEADER_ARTIFACT_DIR_LINE if meta.get("artifact_is_dir") else PATCH_HEADER_ARTIFACT_LINE
        header = "## Required output artifacts\n\n" + line.format(
            path=meta["declared_artifacts"][0], workdir=meta["workdir"]) + "\n"
    else:
        # Same header wording as the word2vec base template (scripts/word2vec_ab_v2_records.py base-template).
        header = (
            "## Required output artifacts\n\n"
            "The official task metadata declares these files as required outputs. "
            "Create the implementation at each exact path so Harbor can collect it:\n"
            + "".join(f"- `{path}`\n" for path in meta["declared_artifacts"])
            + "\n"
        )
    instruction = Path(args.instruction).read_text(encoding="utf-8")
    Path(args.output).write_text(header + instruction, encoding="utf-8")
    print(sha256_file(Path(args.output)))
    return 0


# ---------------------------------------------------------------------- manifest
def cmd_manifest(args: argparse.Namespace) -> int:
    root = Path(args.root)
    rows = []
    for path in root.rglob("*"):
        if path.is_file() and not path.is_symlink():
            rel = path.relative_to(root).as_posix()
            rows.append((rel, sha256_file(path)))
    rows.sort()
    Path(args.output).write_text("".join(f"{sha}  ./{rel}\n" for rel, sha in rows), encoding="utf-8")
    return 0


# ------------------------------------------------------------------ trial-record
def _ctx(ps: dict, model: str):
    for m in ps.get("models") or []:
        if m.get("name") == model or m.get("model") == model:
            return m.get("context_length")
    return None


def cmd_trial_record(args: argparse.Namespace) -> int:
    spec = spec_for(args.task)
    cases_total = spec["cases_total"]
    tdir = Path(args.trial_dir)
    gdir = Path(args.grade_dir)
    job_dir = Path(args.job_dir)
    run_meta = read_json(tdir / "run-meta.json") or {}
    events = read_json(tdir / "events-summary.json") or {}
    audit = read_json(Path(args.audit)) or {}
    ctx_before = read_json(Path(args.ps_before)) or {}
    ctx_after = read_json(Path(args.ps_after)) or {}

    harbor_trials = sorted(p for p in job_dir.glob("*") if p.is_dir()) if job_dir.is_dir() else []
    harbor_trial = harbor_trials[0] if harbor_trials else None
    raw_result = read_json(harbor_trial / "result.json") if harbor_trial else None
    result = raw_result or {}

    artifact = Path(args.artifact_file)
    artifact_exists = artifact.is_file() and artifact.stat().st_size > 0
    artifact_sha = sha256_file(artifact) if artifact_exists else None
    # DAPT: the template is already present, so the artifact counts only if the agent changed it.
    artifact_ok = artifact_exists and (not args.artifact_start_sha or artifact_sha != args.artifact_start_sha)

    patch_mode = spec.get("artifact_mode") == "patch"
    cookie_mode = spec.get("verifier_format") == "cookie-store-text"
    jest_mode = spec.get("verifier_format") == "jest-sections"
    if cookie_mode:
        verifier = parse_cookie_store(harbor_trial / "verifier") if harbor_trial else \
            parse_cookie_store(Path("/nonexistent"))
    elif jest_mode:
        verifier = parse_jest_sections(harbor_trial / "verifier") if harbor_trial else \
            parse_jest_sections(Path("/nonexistent"))
    elif patch_mode:
        verifier = parse_reward_json(harbor_trial / "verifier" / "reward.json") if harbor_trial else \
            parse_reward_json(Path("/nonexistent"))
    else:
        verifier = parse_verifier(harbor_trial / "verifier" / "test-stdout.txt") if harbor_trial else \
            parse_verifier(Path("/nonexistent"))
    reward = None
    if result.get("verifier_result"):
        reward = (result["verifier_result"].get("rewards") or {}).get("reward")
    if reward is None and harbor_trial and (harbor_trial / "verifier" / "reward.txt").is_file():
        try:
            reward = float((harbor_trial / "verifier" / "reward.txt").read_text().strip())
        except ValueError:
            reward = None
    if reward is None and patch_mode and harbor_trial and (harbor_trial / "verifier" / "reward.json").is_file():
        reward = (read_json(harbor_trial / "verifier" / "reward.json") or {}).get("reward")

    exc = result.get("exception_info")
    exc_type = exc.get("exception_type") if isinstance(exc, dict) else None
    try:
        harbor_exit = int(args.harbor_exit)
    except ValueError:
        harbor_exit = None

    turns_started = int(events.get("turns_started", 0) or 0)
    items_completed = int(events.get("items_completed", 0) or 0)
    category, invalid_reason = categorize(
        harbor_exit=harbor_exit, raw_result=raw_result, exc_type=exc_type,
        has_exception=bool(exc), reward=reward, verifier=verifier,
        artifact_present=artifact_ok, agent_steps=items_completed,
        model_requests=turns_started, expect_model=True)
    if category == "CONTRACT_COLLECTION_ERROR" and harbor_trial is not None:
        # A missing attribute is the agent's contract error; any other collection error is COLLECTION_ERROR_OTHER.
        if "AttributeError" not in read_text_or_empty(harbor_trial / "verifier" / "test-stdout.txt"):
            category = "COLLECTION_ERROR_OTHER"
    patch_extra = {}
    if patch_mode:
        # Grading must have seen the same patch the runner saved: compare Harbor's collected file with ours.
        saved = tdir / "model.patch"
        saved_sha = sha256_file(saved) if saved.is_file() else None
        collected_file = harbor_trial / "artifacts" / "logs" / "artifacts" / "model.patch" if harbor_trial else None
        harbor_sha = sha256_file(collected_file) if collected_file and collected_file.is_file() else None
        if category != "INVALID_INFRA" and saved_sha is not None and harbor_sha != saved_sha:
            category, invalid_reason = "INVALID_INFRA", "harbor_collected_patch_mismatch"
        patch_extra = {
            "artifact_mode": "patch",
            "harbor_collected_patch_sha256": harbor_sha,
            "collect_exit_code": int(read_text_or_empty(tdir / "collect-exit.txt").strip() or -1),
            "verifier_reward_json_present": verifier["output_present"] if not (cookie_mode or jest_mode) else None,
            "cases_total_matches_verifier": verifier["collected"] == cases_total,
        }
        if jest_mode:
            patch_extra.update({
                "verifier_format": "jest-sections",
                "functional_reward": verifier["functional_reward"],
                "regression_total": verifier["regression_collected"],
                "regression_passed": verifier["regression"]["passed"],
                "regression_failed": verifier["regression"]["failed"],
                "regression_skipped": verifier["regression"]["skipped"],
                "functional_total": verifier["functional_collected"],
                "functional_passed": verifier["functional"]["passed"],
                "functional_failed": verifier["functional"]["failed"],
                "functional_skipped": verifier["functional"]["skipped"],
                "preference_pass": verifier["preference_pass"],
                "user_preference_json_present": verifier["preference_json_present"],
                "verifier_parse_note": verifier["parse_note"],
            })
        if spec.get("preference_format") == "ctrf-summary":
            patch_extra.update(parse_ctrf_preference(harbor_trial / "verifier" if harbor_trial else Path("/nonexistent")))
        if cookie_mode:
            patch_extra.update({
                "verifier_format": "cookie-store-text",
                "strict_reward_file": (harbor_trial / "verifier" / "reward.txt").is_file() if harbor_trial else False,
                "functional_reward": verifier["functional_reward"],
                "regression_total": verifier["regression_collected"],
                "regression_passed": verifier["regression"]["passed"],
                "regression_failed": verifier["regression"]["failed"],
                "regression_errors": verifier["regression"]["errors"],
                "regression_skipped": verifier["regression"]["skipped"],
                "functional_total": verifier["functional_collected"],
                "functional_passed": verifier["functional"]["passed"],
                "functional_failed": verifier["functional"]["failed"],
                "functional_errors": verifier["functional"]["errors"],
                "functional_skipped": verifier["functional"]["skipped"],
                "preference_gates_pass": verifier["preference_gates_pass"],
                "preference_gates_fail": verifier["preference_gates_fail"],
                "preference_score": verifier["preference_score"],
                "user_preference_json_present": verifier["user_preference_json_present"],
                "verifier_parse_note": verifier["parse_note"],
            })
    valid = category != "INVALID_INFRA"
    cases_passed = strict_reward = None
    if valid:
        strict_reward = 1.0 if category == "PASS" else 0.0
        cases_passed = 0 if category in ZERO_CASES_CATEGORIES else min(verifier["passed"], cases_total)

    usage = events.get("usage") or {}
    provider = "local_ollama-responses" if args.provider_variant == "responses-custom-provider" else "ollama-oss-builtin"
    record = {
        "schema": SCHEMA,
        "task": args.task,
        "job_id": args.job_id,
        "trial_index": args.index,
        "condition": args.condition,
        "arm": args.arm or args.condition,
        "harness": "codex-cli",
        "model": args.model,
        "reasoning_effort": args.reasoning,
        "codex_version": run_meta.get("codex_version"),
        "valid": valid,
        "failure_category": category,
        "invalid_reason": invalid_reason,
        "strict_reward": strict_reward,
        "cases_total": cases_total,
        "cases_passed": cases_passed,
        "verifier_collected": verifier["collected"],
        "verifier_passed": verifier["passed"],
        "verifier_failed": verifier["failed"],
        "verifier_errors": verifier["errors"],
        "verifier_collection_error": verifier["collection_error"],
        "verifier_network_mode": "public",
        "artifact_present": artifact_ok,
        "artifact_rel_sha256_start": args.artifact_start_sha or None,
        "artifact_final_sha256": artifact_sha,
        "harbor_grading_exit_code": harbor_exit,
        "harbor_exception_type": exc_type,
        "reward_raw": reward,
        "codex_exit_code": run_meta.get("codex_exit_code"),
        "timed_out": run_meta.get("timed_out"),
        "agent_timeout_sec": args.agent_timeout_sec,
        "agent_wall_sec": run_meta.get("agent_wall_sec"),
        "turns_started": turns_started,
        "turns_completed": events.get("turns_completed"),
        "turns_failed": events.get("turns_failed"),
        "commands_executed": events.get("commands_executed"),
        "file_change_items": events.get("file_change_items"),
        "file_change_entries": events.get("file_change_entries"),
        "items_completed": items_completed,
        "input_tokens": usage.get("input_tokens"),
        "cached_input_tokens": usage.get("cached_input_tokens"),
        "output_tokens": usage.get("output_tokens"),
        "reasoning_output_tokens": usage.get("reasoning_output_tokens"),
        "token_source": events.get("usage_source"),
        "prompt_sha256": run_meta.get("prompt_sha256"),
        "memory_sha256": run_meta.get("memory_sha256") or None,
        "codex_config_sha256": run_meta.get("config_sha256"),
        "auth_refreshed": run_meta.get("auth_refreshed"),
        "auth_copied_back": run_meta.get("auth_copied_back"),
        "auth_file_present": False,
        "openai_credentials_mounted": False,
        "provider": provider,
        "provider_variant": args.provider_variant,
        "provider_base_url_host": args.base_url_host,
        "codex_model_provider_source": "config.toml" if args.provider_variant == "responses-custom-provider" else "--oss",
        "ollama_model": args.model,
        "ollama_num_ctx_loaded_before": _ctx(ctx_before, args.model),
        "ollama_num_ctx_loaded_after": _ctx(ctx_after, args.model),
        "ollama_effort_audit": audit,
        "temperature_setting": "not settable in Codex 0.157 (no config key); Ollama default used",
        "memory_mode": args.memory_mode,
        "network_egress_isolation_enforced": False,
    }
    record.update(patch_extra)
    if args.task == "build-word2vec-pipeline":
        record["cases_passed_of_6"] = cases_passed  # kept only for word2vec compatibility
    out = Path(args.output) if args.output else tdir / "trial-record.json"
    out.write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({k: record[k] for k in ("trial_index", "condition", "valid", "failure_category",
                                             "strict_reward", "cases_passed", "cases_total",
                                             "verifier_collected")}))
    return 0


# -------------------------------------------------------------------- verify-memory
def cmd_verify_memory(args: argparse.Namespace) -> int:
    # Same check as frontier_memory.memory.check_memory (stdlib only). Prints counts and the digest, never content.
    sys.path.insert(0, str(HERE.parent / "frontiermemory" / "src"))
    from frontier_memory.memory import check_memory  # noqa: E402

    report = check_memory(Path(args.memory_dir).expanduser().resolve())
    if not report["ok"]:
        raise SystemExit(f"arm {args.name}: memory folder is invalid ({len(report['errors'])} check errors)")
    digest = report["memory_sha256"]
    if digest != args.expected_digest:
        raise SystemExit(f"arm {args.name}: memory digest {digest} does not match the expected digest")
    print(json.dumps({"arm": args.name, "memory_sha256": digest, "file_count": report["file_count"],
                      "total_bytes": report["total_bytes"]}))
    return 0


# ------------------------------------------------------------------ balanced-order
def balanced_order(arms: list[str], rounds: int) -> list[str]:
    """Round r uses the arms list rotated left by r (r = 0, 1, ...). Each arm appears once per round."""
    if len(set(arms)) != len(arms) or not arms:
        raise SystemExit("arms must be non-empty and distinct")
    order: list[str] = []
    for r in range(rounds):
        k = r % len(arms)
        order.extend(arms[k:] + arms[:k])
    return order


def cmd_balanced_order(args: argparse.Namespace) -> int:
    arms = [a.strip() for a in args.arms.split(",") if a.strip()]
    order = balanced_order(arms, args.rounds)
    print(f'TRIAL_ORDER="{" ".join(order)}"')
    print(f"# {len(order)} trials; {args.rounds} rounds; each arm {args.rounds} times; "
          f"round r = arms rotated left by r")
    return 0


# ----------------------------------------------------------------------- aggregate
def cmd_aggregate(args: argparse.Namespace) -> int:
    run_dir = Path(args.run_dir)
    records = [json.loads(p.read_text(encoding="utf-8")) for p in sorted(run_dir.glob("trial-*/trial-record.json"))]
    records.sort(key=lambda r: r["trial_index"])
    groups: dict[str, dict] = {}
    for r in records:
        arm = r.get("arm") or r.get("condition")
        g = groups.setdefault(arm, {"arm": arm, "condition": r.get("condition"), "trial_indices": [],
                                    "trials": 0, "valid": 0, "strict_reward_sum": 0.0,
                                    "cases_passed_sum": 0, "cases_total": r.get("cases_total"),
                                    "failure_categories": {}})
        g["trial_indices"].append(r["trial_index"])
        g["trials"] += 1
        if r.get("valid"):
            g["valid"] += 1
            g["strict_reward_sum"] += float(r.get("strict_reward") or 0.0)
            g["cases_passed_sum"] += int(r.get("cases_passed") or 0)
        cat = r.get("failure_category") or "UNKNOWN"
        g["failure_categories"][cat] = g["failure_categories"].get(cat, 0) + 1
    by_arm = []
    for arm in sorted(groups, key=lambda a: groups[a]["trial_indices"][0]):
        g = groups[arm]
        g["strict_reward_mean"] = g["strict_reward_sum"] / g["valid"] if g["valid"] else None
        g["cases_passed_mean"] = g["cases_passed_sum"] / g["valid"] if g["valid"] else None
        by_arm.append(g)
    (run_dir / "trials-summary.json").write_text(
        json.dumps({"job_id": args.job_id, "trial_order": args.trial_order, "by_arm": by_arm, "trials": records},
                   indent=2) + "\n", encoding="utf-8")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("task-meta")
    p.add_argument("--task", required=True)
    p.add_argument("--task-toml", required=True)
    p.add_argument("--output", required=True)
    p.set_defaults(func=cmd_task_meta)

    p = sub.add_parser("render-prompt")
    p.add_argument("--task-meta", required=True)
    p.add_argument("--instruction", required=True)
    p.add_argument("--output", required=True)
    p.set_defaults(func=cmd_render_prompt)

    p = sub.add_parser("manifest")
    p.add_argument("--root", required=True)
    p.add_argument("--output", required=True)
    p.set_defaults(func=cmd_manifest)

    p = sub.add_parser("trial-record")
    p.add_argument("--task", required=True)
    p.add_argument("--trial-dir", required=True)
    p.add_argument("--grade-dir", required=True)
    p.add_argument("--job-dir", required=True)
    p.add_argument("--job-id", required=True)
    p.add_argument("--index", type=int, required=True)
    p.add_argument("--condition", required=True, choices=["A", "B"])
    p.add_argument("--arm", default="", help="arm name (A0, A, B, or a MEMORY_ARMS name); defaults to --condition")
    p.add_argument("--model", required=True)
    p.add_argument("--reasoning", required=True)
    p.add_argument("--harbor-exit", required=True)
    p.add_argument("--agent-timeout-sec", type=float, required=True)
    p.add_argument("--artifact-file", required=True)
    p.add_argument("--artifact-start-sha", default="")
    p.add_argument("--provider-variant", required=True)
    p.add_argument("--base-url-host", required=True)
    p.add_argument("--memory-mode", required=True)
    p.add_argument("--audit", required=True)
    p.add_argument("--ps-before", required=True)
    p.add_argument("--ps-after", required=True)
    p.add_argument("--output")
    p.set_defaults(func=cmd_trial_record)

    p = sub.add_parser("verify-memory")
    p.add_argument("--name", required=True)
    p.add_argument("--memory-dir", required=True)
    p.add_argument("--expected-digest", required=True)
    p.set_defaults(func=cmd_verify_memory)

    p = sub.add_parser("balanced-order")
    p.add_argument("--arms", default=",".join(PREREG_ARMS))
    p.add_argument("--rounds", type=int, default=PREREG_ROUNDS)
    p.set_defaults(func=cmd_balanced_order)

    p = sub.add_parser("add-verifier-env")
    p.add_argument("--task", required=True)
    p.add_argument("--task-toml", required=True)
    p.set_defaults(func=cmd_add_verifier_env)

    p = sub.add_parser("aggregate")
    p.add_argument("--run-dir", required=True)
    p.add_argument("--job-id", required=True)
    p.add_argument("--trial-order", required=True)
    p.set_defaults(func=cmd_aggregate)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
