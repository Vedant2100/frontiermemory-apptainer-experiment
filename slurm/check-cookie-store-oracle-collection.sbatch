#!/usr/bin/env bash
#SBATCH --job-name=fm-cookie-oracle-check
#SBATCH --partition=batch
#SBATCH --cpus-per-task=4
#SBATCH --mem=16G
#SBATCH --time=03:00:00
#SBATCH --output=logs/cookie-store-oracle-check-%j.out
#SBATCH --error=logs/cookie-store-oracle-check-%j.err
# CPU-only grading check for cookie-store-compositional-changelog (patch artifact). No model, Ollama, or GPU.
# Same structure as slurm/check-cattrs-oracle-collection.sbatch. The verifier test.sh installs its pinned
# dependencies from /opt/verifier-wheels with --no-index, so this check needs no network.
#   nop          Harbor's nop agent on the unmodified base repository. The task's collect step yields an empty
#                patch. Expect reward 0.
#   oracle       Harbor's oracle agent runs the task's reference solution in its agent container, as the DAPT
#                oracle check does. Expect every functional and regression case to pass. The user-preference check
#                is expected to fail for the reference solution (it implements only the functional change), so the
#                reward may be 0 as it was for cattrs. Counts are reported per category, not per test name.
#   scratch-nop  The reference solution applied to a scratch copy of the repository and committed, then collected
#                with the task's collect command. Graded by the nop agent with that copy bound at /app, which is the
#                patch-task grading path of scripts/run_codex_ollama_trial.sh. Expect the same counts as oracle.
# Only counts, sizes, and hashes go into the run directory (gitignored). Verifier output, patches, and the solution
# text stay in Harbor's jobs/ directory and in build/ (both gitignored) and are not printed or copied.
set -euo pipefail
cd /home/csgrad/vbork001/frontiermemory-experiment-20261024
export PATH="${PWD}/bin:${PATH}"
export APPTAINER_CACHEDIR="${PWD}/containers/apptainer-cache"
PY="${PWD}/.venv/bin/python"

TASK_NAME=cookie-store-compositional-changelog
# 1 = declare safe.directory for the verifier's git through its environment (see run_harbor).
VERIFIER_GIT_SAFE_ENV="${VERIFIER_GIT_SAFE_ENV:-1}"
# Under fakeroot the verifier's root process inherits USER=agent, so pytest names its root-owned temp dir
# pytest-of-agent and the later runuser-agent pytest rejects it. USER/LOGNAME=root restores what Docker gives root.
# (VERIFIER_TMP is unused by the env block now.)
VERIFIER_TMP="/tmp/fm-cookie-verifier-${SLURM_JOB_ID}"
SOURCE_TASK="${PWD}/data/tasks/frontier-memory/${TASK_NAME}"
AGENT_SIF="${PWD}/containers/frontier-memory-cookie-store.sif"
VERIFIER_SIF="${VERIFIER_SIF:-${PWD}/containers/frontier-memory-cookie-store-verifier-v2.sif}"
VENV_SOURCE="${PWD}/runtime/openhands-sdk-venv"
PYTHON_SOURCE="${PWD}/runtime/uv/python/cpython-3.12-linux-x86_64-gnu"
# Same shared Harbor server runtime as the DAPT oracle check.
HARBOR_SHARED_BINDPATH="${PYTHON_SOURCE}:${PYTHON_SOURCE},${VENV_SOURCE}:/opt/harbor-server"
HARBOR_WRAPPER="${PWD}/scripts/harbor_singularity_exec_timeout.py"
export HARBOR_SINGULARITY_EXEC_TIMEOUT_SEC="${HARBOR_SINGULARITY_EXEC_TIMEOUT_SEC:-7200}"
RUN_DIR="${PWD}/results/cookie-store-oracle-check-${SLURM_JOB_ID}"
BUILD_ROOT="${PWD}/build/cookie-store-apptainer/oracle-check/job-${SLURM_JOB_ID}"
HARBOR_BASE_NAME="frontiermemory-cookie-oracle-check-${SLURM_JOB_ID}"
JOBS_DIR="${PWD}/jobs"

# Refuse to build or download anything: every image must already exist.
test -s "${AGENT_SIF}" && test -s "${VERIFIER_SIF}" && test -d "${SOURCE_TASK}" && test -s "${HARBOR_WRAPPER}"
test -x "${VENV_SOURCE}/bin/python" && test -x "${PYTHON_SOURCE}/bin/python3.12"
mkdir -p "${RUN_DIR}" "${BUILD_ROOT}" logs
date --iso-8601=seconds >"${RUN_DIR}/started-at.txt"
mkdir -p "${VERIFIER_TMP}" && chmod 1777 "${VERIFIER_TMP}"
scontrol show job "${SLURM_JOB_ID}" >"${RUN_DIR}/slurm-job.txt"
.venv/bin/harbor --version >"${RUN_DIR}/harbor-version.txt"
sha256sum "${HARBOR_WRAPPER}" >"${RUN_DIR}/harbor-wrapper-sha256.txt"
printf 'HARBOR_SINGULARITY_EXEC_TIMEOUT_SEC=%s\n' "${HARBOR_SINGULARITY_EXEC_TIMEOUT_SEC}" >"${RUN_DIR}/harbor-exec-timeout.txt"
apptainer version >"${RUN_DIR}/apptainer-version.txt"

# Hashing only: official task file hashes and verifier test-file hashes in the verifier image.
(cd "${SOURCE_TASK}" && find . -type f -print0 | sort -z | xargs -0 sha256sum) >"${RUN_DIR}/official-task-sha256.txt"
(cd "${SOURCE_TASK}/tests" && find . -type f -print0 | sort -z | xargs -0 sha256sum) >"${RUN_DIR}/verifier-source-tests-sha256.txt"
sha256sum "${VERIFIER_SIF}" >"${RUN_DIR}/verifier-image-sha256.txt"
apptainer exec --fakeroot --pwd /tests "${VERIFIER_SIF}" /bin/bash -c \
  'cd /tests && find . -type f -print0 | sort -z | xargs -0 sha256sum' >"${RUN_DIR}/verifier-image-tests-sha256.txt"
if ! diff <(sort "${RUN_DIR}/verifier-source-tests-sha256.txt") <(sort "${RUN_DIR}/verifier-image-tests-sha256.txt") >/dev/null; then
  echo "Verifier SIF test files differ from the pinned task source" >&2; exit 1
fi
apptainer exec --fakeroot --pwd /tests "${VERIFIER_SIF}" /bin/bash -c \
  'test -x /tests/test.sh && command -v python3 && python3 -c "import sys; print(\"verifier-python\", sys.version.split()[0])"' \
  >"${RUN_DIR}/verifier-image-preflight.txt" 2>&1 || true

# Agent image: the repository must sit at the task base commit, and the httpx package must import.
BASE_COMMIT="$("${PY}" -c 'import sys,tomllib; print(tomllib.load(open(sys.argv[1],"rb"))["metadata"]["base_commit_hash"])' "${SOURCE_TASK}/task.toml")"
COLLECT_COMMAND="$("${PY}" -c 'import sys,tomllib; print(tomllib.load(open(sys.argv[1],"rb"))["verifier"]["collect"][0]["command"])' "${SOURCE_TASK}/task.toml")"
apptainer exec --fakeroot --writable-tmpfs --containall --no-mount home,tmp,bind-paths --pwd /app "${AGENT_SIF}" /bin/bash -c \
  'git -C /app rev-parse HEAD && python3 -c "import httpx,sys; print(\"agent-python\", sys.version.split()[0])"' \
  >"${RUN_DIR}/agent-runtime-preflight.txt" 2>&1
grep -qx "${BASE_COMMIT}" "${RUN_DIR}/agent-runtime-preflight.txt" || {
  echo "Agent image /app is not at the task base commit" >&2; exit 1
}

# Stage one Harbor run: a fresh staged task copy (only images and the verifier network mode change), then Harbor.
run_harbor() {  # $1 = trial name, $2 = Harbor agent, $3 = --mounts-json
  local name="$1" agent="$2" mounts="$3"
  local task_path="${BUILD_ROOT}/${name}/${TASK_NAME}"
  local job_name="${HARBOR_BASE_NAME}-${name}"
  local exit_code
  mkdir -p "${RUN_DIR}/${name}"
  date --iso-8601=seconds >"${RUN_DIR}/${name}/started-at.txt"
  "${PY}" scripts/stage_word2vec_task_for_apptainer.py --source "${SOURCE_TASK}" --output "${task_path}" \
    --agent-image "${AGENT_SIF}" --verifier-image "${VERIFIER_SIF}" >"${RUN_DIR}/${name}/task-staging.json"
  # Git in the verifier runs as the agent user, and the verifier's /app is owned by the Harbor user, so git rejects
  # the repository (safe.directory) and the reset step cannot restore tests/conftest.py. Declare safe.directory for
  # every git process through the environment; test.sh, original-test.sh and the tests stay unchanged.
  if [[ "${VERIFIER_GIT_SAFE_ENV}" == 1 ]]; then
    "${PY}" -c 'import sys; from pathlib import Path; p = Path(sys.argv[1]); t = p.read_text(encoding="utf-8"); h = "[verifier.env]\n"; assert t.count(h) == 1, "expected one [verifier.env] table"; e = "GIT_CONFIG_COUNT = \"1\"\nGIT_CONFIG_KEY_0 = \"safe.directory\"\nGIT_CONFIG_VALUE_0 = \"*\"\nUSER = \"root\"\nLOGNAME = \"root\"\n"; p.write_text(t.replace(h, h + e, 1), encoding="utf-8")' "${task_path}/task.toml" "${VERIFIER_TMP}"
  fi
  "${PY}" - "${task_path}/task.toml" "${SOURCE_TASK}/task.toml" <<'PY'
import sys, tomllib
staged, official = (tomllib.loads(open(path, encoding="utf-8").read()) for path in sys.argv[1:])
if staged["verifier"]["environment"]["network_mode"] != "public":
    raise SystemExit("staged verifier network_mode must be public")
if staged.get("artifacts") != ["/logs/artifacts/model.patch"]:
    raise SystemExit("unexpected artifact metadata")
if staged["verifier"]["collect"] != official["verifier"]["collect"]:
    raise SystemExit("collect command changed by staging")
PY
  set +e
  APPTAINER_BINDPATH="${HARBOR_SHARED_BINDPATH}" SINGULARITY_BINDPATH="${HARBOR_SHARED_BINDPATH}" \
    timeout --signal=INT --kill-after=20s 2700s "${PY}" "${HARBOR_WRAPPER}" run --path "${task_path}" \
    --env singularity --mounts-json "${mounts}" --jobs-dir jobs --job-name "${job_name}" --agent "${agent}" \
    --n-attempts 1 --n-concurrent 1 --agent-timeout-multiplier 1.0 --agent-setup-timeout-multiplier 0.5 --yes \
    >"${RUN_DIR}/${name}/harbor.log" 2>&1
  exit_code=$?
  set -e
  printf '%s\n' "${exit_code}" >"${RUN_DIR}/${name}/harbor-exit-code.txt"
  date --iso-8601=seconds >"${RUN_DIR}/${name}/finished-at.txt"
  echo "${name} agent=${agent} harbor_exit=${exit_code}"
}

run_harbor nop nop '[]'
run_harbor oracle oracle '[]'

# Scratch copy: populate from the image /app (same tar stream as the runner), apply the reference solution with
# git apply --index, commit it (the collect command reads HEAD), then run the collect command as the runner does.
SCRATCH_DIR="${BUILD_ROOT}/scratch"
SCRATCH="${SCRATCH_DIR}/app"
rm -rf "${SCRATCH_DIR}"
mkdir -p "${SCRATCH}" "${SCRATCH_DIR}/logs" "${SCRATCH_DIR}/home"
chmod 755 "${SCRATCH}"
apptainer exec --containall --cleanenv --no-home --pwd /app "${AGENT_SIF}" tar -C /app -cf - . \
  | tar -C "${SCRATCH}" -xf -
# The copied .git/index has stale stat data, so refresh it before --index (content is unchanged).
git -C "${SCRATCH}" update-index -q --refresh || true
git -C "${SCRATCH}" apply --index --whitespace=nowarn "${SOURCE_TASK}/solution/solution.patch"
git -C "${SCRATCH}" -c user.name=oracle-check -c user.email=oracle-check@localhost commit -q -m "oracle check"
chmod 700 "${SCRATCH_DIR}/home"
set +e
timeout --signal=INT --kill-after=30s 300s apptainer exec --containall --cleanenv --writable-tmpfs \
  --home "${SCRATCH_DIR}/home:/collect-home" --pwd /app --bind "${SCRATCH}:/app" --bind "${SCRATCH_DIR}/logs:/logs" \
  "${AGENT_SIF}" /bin/bash -c "${COLLECT_COMMAND}" >"${SCRATCH_DIR}/collect-stdout.txt" 2>"${SCRATCH_DIR}/collect-stderr.txt"
collect_rc=$?
set -e
printf '%s\n' "${collect_rc}" >"${RUN_DIR}/scratch-collect-exit.txt"
cp -a "${SCRATCH}" "${SCRATCH_DIR}/app-graded"
MOUNTS_SCRATCH="$("${PY}" -c 'import json,sys; print(json.dumps([{"type":"bind","source":sys.argv[1],"target":"/app"}]))' "${SCRATCH_DIR}/app-graded")"
run_harbor scratch-nop nop "${MOUNTS_SCRATCH}"

# Counts, sizes, and hashes only. The collected patches are hashed, never printed. Test names are never printed.
local_patch="${SCRATCH_DIR}/logs/artifacts/model.patch"
"${PY}" - "${RUN_DIR}" "${JOBS_DIR}" "${HARBOR_BASE_NAME}" "${local_patch}" <<'PY'
import hashlib, json, re, sys
from pathlib import Path

run_dir, jobs_dir, base, local_patch = Path(sys.argv[1]), Path(sys.argv[2]), sys.argv[3], Path(sys.argv[4])
# pytest summary line, e.g. "1284 passed, 4 skipped, 1 error in 12.74s" (decorations optional). Counts only.
SUMMARY_RE = re.compile(r"^=*\s*((?:\d+ [a-z]+,? ?)+) in [0-9.]+s")

def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else None

def pytest_counts(text):
    # test.sh runs "base" (regression) first, then "new" (functional). Each run prints one summary line.
    runs = []
    for line in text.splitlines():
        m = SUMMARY_RE.match(line.strip())
        if m:
            counts = {}
            for n, word in re.findall(r"(\d+) ([a-z]+)", m.group(1)):
                counts[word.rstrip("s") if word in ("errors",) else word] = int(n)
            runs.append(counts)
    def cases(c):
        return {"passed": c.get("passed", 0), "failed": c.get("failed", 0), "errors": c.get("error", 0),
                "skipped": c.get("skipped", 0)}
    out = {"regression": cases(runs[0]) if len(runs) > 0 else None,
           "functional": cases(runs[1]) if len(runs) > 1 else None}
    return out

def trial(name):
    job = jobs_dir / f"{base}-{name}"
    dirs = sorted(p for p in job.glob("*") if p.is_dir()) if job.is_dir() else []
    if not dirs:
        return {"harbor_trial_found": False}
    t = dirs[0]
    result = json.loads((t / "result.json").read_text()) if (t / "result.json").is_file() else {}
    vdir = t / "verifier"
    def read(name_):
        p = vdir / name_
        return p.read_text().strip() if p.is_file() else None
    reward = read("reward.txt")
    text = (vdir / "test-stdout.txt").read_text(errors="replace") if (vdir / "test-stdout.txt").is_file() else ""
    patch = t / "artifacts" / "logs" / "artifacts" / "model.patch"
    pref = {"gates_pass": len(re.findall(r"^\[user-preference-gate\] PASS", text, re.M)),
            "gates_fail": len(re.findall(r"^\[user-preference-gate\] FAIL", text, re.M)),
            "score": read("user-preference-score.txt")}
    exc = (result.get("exception_info") or {}).get("exception_type")
    return {
        "harbor_trial_found": True, "reward": int(float(reward)) if reward not in (None, "") else None,
        "functional_reward": read("functional-reward.txt"), "exception_type": exc,
        "pytest": pytest_counts(text), "preference": pref,
        "collected_patch_bytes": patch.stat().st_size if patch.is_file() else None,
        "collected_patch_sha256": sha(patch),
    }

summary = {name: trial(name) for name in ("nop", "oracle", "scratch-nop")}
summary["local_scratch_collect_exit"] = int((run_dir / "scratch-collect-exit.txt").read_text().strip() or -1)
summary["local_scratch_patch_bytes"] = local_patch.stat().st_size if local_patch.is_file() else None
summary["local_scratch_patch_sha256"] = sha(local_patch)
oracle = summary["oracle"]
o_py = oracle.get("pytest") or {}
reg, fun = o_py.get("regression"), o_py.get("functional")
def clean(c):
    return c is not None and c["failed"] == 0 and c["errors"] == 0 and c["passed"] > 0
checks = {
    "nop_reward_0_empty_patch": summary["nop"].get("reward") == 0 and summary["nop"].get("collected_patch_bytes") == 0,
    "oracle_functional_all_pass": clean(fun),
    "oracle_regression_all_pass": clean(reg),
    "scratch_collected_matches_local": summary["local_scratch_patch_sha256"] is not None
        and summary["scratch-nop"].get("collected_patch_sha256") == summary["local_scratch_patch_sha256"],
    "scratch_pytest_matches_oracle": summary["scratch-nop"].get("pytest") == o_py,
}
# Cases per category, derived from the oracle run (passed + failed + errors; skipped reported separately).
summary["cases_total_from_oracle"] = sum(c["passed"] + c["failed"] + c["errors"] for c in (reg, fun) if c)
summary["checks"] = checks
summary["verdict"] = "PASS" if all(checks.values()) else "FAIL"
(run_dir / "summary.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
print(json.dumps({"verdict": summary["verdict"], "checks": checks,
                  "cases_total_from_oracle": summary["cases_total_from_oracle"]}))
sys.exit(0 if summary["verdict"] == "PASS" else 1)
PY
date --iso-8601=seconds >"${RUN_DIR}/finished-at.txt"
