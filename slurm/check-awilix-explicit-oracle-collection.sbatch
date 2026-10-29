#!/usr/bin/env bash
#SBATCH --job-name=fm-awilix-explicit-oracle
#SBATCH --partition=batch
#SBATCH --cpus-per-task=4
#SBATCH --mem=16G
#SBATCH --time=03:00:00
#SBATCH --output=logs/awilix-explicit-oracle-check-%j.out
#SBATCH --error=logs/awilix-explicit-oracle-check-%j.err
# CPU-only grading check for awilix-release-tier-explicit (patch artifact, Jest verifier). No model, Ollama, or GPU.
# Same structure as slurm/check-cookie-store-oracle-collection.sbatch (Harbor nop / oracle / scratch-nop).
#   nop          Harbor's nop agent on the unmodified base. The task's collect step yields an empty patch.
#                Expect reward 0 and no functional cases passing.
#   oracle       Harbor's oracle agent runs the reference solution in its agent container. Expect every functional
#                and regression case to pass. The user-preference check may fail for the reference (by design).
#   scratch-nop  The reference solution applied to a scratch copy, committed, then collected with the task's collect
#                command and graded by the nop agent with that copy bound at /app (the patch-task grading path of
#                scripts/run_codex_ollama_trial.sh). Expect the same counts as oracle.
# Only counts, sizes, and hashes go into the run directory (gitignored). Verifier output, patches, and the solution
# text stay in Harbor's jobs/ directory and in build/ (both gitignored) and are not printed or copied.
set -euo pipefail
cd /home/csgrad/vbork001/frontiermemory-experiment-20261024
export PATH="${PWD}/bin:${PATH}"
export APPTAINER_CACHEDIR="${PWD}/containers/apptainer-cache"
PY="${PWD}/.venv/bin/python"

TASK_NAME=awilix-release-tier-explicit
AGENT_SIF="${PWD}/containers/awilix-release-tier-explicit.sif"
VERIFIER_SIF="${VERIFIER_SIF:-${PWD}/containers/awilix-release-tier-explicit-verifier.sif}"
SOURCE_TASK="${PWD}/data/tasks/frontier-memory/${TASK_NAME}"
VENV_SOURCE="${PWD}/runtime/openhands-sdk-venv"
PYTHON_SOURCE="${PWD}/runtime/uv/python/cpython-3.12-linux-x86_64-gnu"
HARBOR_SHARED_BINDPATH="${PYTHON_SOURCE}:${PYTHON_SOURCE},${VENV_SOURCE}:/opt/harbor-server"
HARBOR_WRAPPER="${PWD}/scripts/harbor_singularity_exec_timeout.py"
export HARBOR_SINGULARITY_EXEC_TIMEOUT_SEC="${HARBOR_SINGULARITY_EXEC_TIMEOUT_SEC:-7200}"
RUN_DIR="${PWD}/results/awilix-explicit-oracle-check-${SLURM_JOB_ID}"
BUILD_ROOT="${PWD}/build/awilix-explicit/oracle-check/job-${SLURM_JOB_ID}"
HARBOR_BASE_NAME="frontiermemory-awilix-explicit-oracle-check-${SLURM_JOB_ID}"
JOBS_DIR="${PWD}/jobs"

# Refuse to build or download anything: every image must already exist.
test -s "${AGENT_SIF}" && test -s "${VERIFIER_SIF}" && test -d "${SOURCE_TASK}" && test -s "${HARBOR_WRAPPER}"
test -x "${VENV_SOURCE}/bin/python" && test -x "${PYTHON_SOURCE}/bin/python3.12"
mkdir -p "${RUN_DIR}" "${BUILD_ROOT}" logs
date --iso-8601=seconds >"${RUN_DIR}/started-at.txt"
scontrol show job "${SLURM_JOB_ID}" >"${RUN_DIR}/slurm-job.txt"
.venv/bin/harbor --version >"${RUN_DIR}/harbor-version.txt"
sha256sum "${HARBOR_WRAPPER}" >"${RUN_DIR}/harbor-wrapper-sha256.txt"
printf 'HARBOR_SINGULARITY_EXEC_TIMEOUT_SEC=%s\n' "${HARBOR_SINGULARITY_EXEC_TIMEOUT_SEC}" >"${RUN_DIR}/harbor-exec-timeout.txt"
apptainer version >"${RUN_DIR}/apptainer-version.txt"

# Hashing only: official task file hashes, verifier test-file hashes in the verifier image, and the image hashes.
(cd "${SOURCE_TASK}" && find . -type f -print0 | sort -z | xargs -0 sha256sum) >"${RUN_DIR}/official-task-sha256.txt"
(cd "${SOURCE_TASK}/tests" && find . -type f -print0 | sort -z | xargs -0 sha256sum) >"${RUN_DIR}/verifier-source-tests-sha256.txt"
sha256sum "${AGENT_SIF}" "${VERIFIER_SIF}" >"${RUN_DIR}/image-sha256.txt"
apptainer exec --fakeroot --pwd /tests "${VERIFIER_SIF}" /bin/bash -c \
  'cd /tests && find . -type f -print0 | sort -z | xargs -0 sha256sum' >"${RUN_DIR}/verifier-image-tests-sha256.txt"
if ! diff <(sort "${RUN_DIR}/verifier-source-tests-sha256.txt") <(sort "${RUN_DIR}/verifier-image-tests-sha256.txt") >/dev/null; then
  echo "Verifier SIF test files differ from the pinned task source" >&2; exit 1
fi
apptainer exec --fakeroot --pwd /tests "${VERIFIER_SIF}" /bin/bash -c \
  'test -x /tests/test.sh && test -x /tests/original-test.sh && id agent && command -v runuser' \
  >"${RUN_DIR}/verifier-image-preflight.txt" 2>&1
# Agent image: the base commit is an ancestor of HEAD, HEAD equals the commit the collect step resets to, node and
# node_modules are present (no network at grading time).
COLLECT_COMMAND="$("${PY}" -c 'import sys,tomllib; print(tomllib.load(open(sys.argv[1],"rb"))["verifier"]["collect"][0]["command"])' "${SOURCE_TASK}/task.toml")"
COLLECT_REF="$(printf '%s\n' "${COLLECT_COMMAND}" | sed -n 's/.*git reset --soft \([^ ]*\) .*/\1/p')"
BASE_COMMIT="$("${PY}" -c 'import sys,tomllib; print(tomllib.load(open(sys.argv[1],"rb"))["metadata"]["base_commit_hash"])' "${SOURCE_TASK}/task.toml")"
apptainer exec --fakeroot --writable-tmpfs --containall --no-mount home,tmp,bind-paths --pwd /app "${AGENT_SIF}" /bin/bash -c \
  "git -C /app rev-parse HEAD && git -C /app rev-parse --verify '${COLLECT_REF}^{commit}' && git -C /app merge-base --is-ancestor '${BASE_COMMIT}' HEAD && test -d /app/node_modules && node -v && npm -v" \
  >"${RUN_DIR}/agent-runtime-preflight.txt" 2>"${RUN_DIR}/agent-runtime-preflight.stderr"
"${PY}" - "${RUN_DIR}/agent-runtime-preflight.txt" <<'PY' || { echo "Agent image /app preflight failed" >&2; exit 1; }
import sys
lines = open(sys.argv[1]).read().split()
head, ref = lines[0], lines[1]
assert head == ref, "HEAD must equal the collect reset ref"
assert lines[2].startswith("v") and lines[3].strip(), "node/npm versions missing"
PY

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

# Scratch copy: populate from the image /app, apply the reference solution with git apply --index, commit it (the
# collect command reads HEAD), then run the collect command as the runner does.
SCRATCH_DIR="${BUILD_ROOT}/scratch"
SCRATCH="${SCRATCH_DIR}/app"
rm -rf "${SCRATCH_DIR}"
mkdir -p "${SCRATCH}" "${SCRATCH_DIR}/logs" "${SCRATCH_DIR}/home"
chmod 755 "${SCRATCH}"
apptainer exec --containall --cleanenv --no-home --pwd /app "${AGENT_SIF}" tar -C /app -cf - . \
  | tar -C "${SCRATCH}" -xf -
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

def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else None

ANSI = re.compile(r"\x1b\[[0-9;]*[A-Za-z]")
JEST_TESTS = re.compile(r"^\s*Tests:\s+(.*)$", re.M)
COUNT = re.compile(r"(\d+) (passed|failed|skipped|todo|pending|total)")

def section_counts(text):
    # Jest summary line, e.g. "Tests:       1 failed, 40 passed, 41 total". The last one in the section is the run's.
    lines = JEST_TESTS.findall(ANSI.sub("", text))
    counts = {"passed": 0, "failed": 0, "skipped": 0, "total": 0}
    if not lines:
        return {"summary_lines": 0, **counts}
    for number, kind in COUNT.findall(lines[-1]):
        counts["skipped" if kind in ("todo", "pending") else kind] += int(number)
    return {"summary_lines": len(lines), **counts}

def verifier_counts(text):
    # test.sh base (regression) runs before "Step 4" and new (functional) after it; both sections are in test-stdout.
    text = ANSI.sub("", text)
    head, sep, tail = text.partition("--- Step 4: Running new tests ---")
    regression = head.partition("--- Step 3: Running baseline tests ---")[2] if sep else head
    functional = tail if sep else ""
    return {"regression": section_counts(regression), "functional": section_counts(functional)}

def clean(counts):
    return counts["summary_lines"] > 0 and counts["failed"] == 0 and counts["passed"] > 0

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
    exc = (result.get("exception_info") or {}).get("exception_type")
    patch_files = sorted(set(re.findall(r"^diff --git a/(\S+) b/", patch.read_text(errors="replace"), re.M))) \
        if patch.is_file() else None
    return {
        "harbor_trial_found": True, "reward": int(float(reward)) if reward not in (None, "") else None,
        "collected_patch_files": patch_files,
        "functional_reward": read("functional-reward.txt"), "exception_type": exc,
        "verifier_counts": verifier_counts(text),
        "collected_patch_bytes": patch.stat().st_size if patch.is_file() else None,
        "collected_patch_sha256": sha(patch),
    }

summary = {name: trial(name) for name in ("nop", "oracle", "scratch-nop")}
summary["local_scratch_collect_exit"] = int((run_dir / "scratch-collect-exit.txt").read_text().strip() or -1)
summary["local_scratch_patch_bytes"] = local_patch.stat().st_size if local_patch.is_file() else None
summary["local_scratch_patch_sha256"] = sha(local_patch)
oracle = summary["oracle"].get("verifier_counts") or {"regression": {}, "functional": {}}
checks = {
    "nop_reward_0": summary["nop"].get("reward") == 0,
    # The image's own working tree has a modified package-lock.json (npm install at image build), so the collect step
    # on an untouched repository yields a patch that changes only that file. Anything else would be a failure.
    "nop_patch_lockfile_only": set(summary["nop"].get("collected_patch_files") or []) <= {"package-lock.json"},
    "nop_no_functional_pass": (summary["nop"].get("verifier_counts") or {"functional": {"passed": 0}})["functional"]["passed"] == 0,
    "oracle_functional_all_pass": clean(oracle["functional"]),
    "oracle_regression_all_pass": clean(oracle["regression"]),
    "scratch_collected_matches_local": summary["local_scratch_patch_sha256"] is not None
        and summary["scratch-nop"].get("collected_patch_sha256") == summary["local_scratch_patch_sha256"],
    "scratch_counts_match_oracle": summary["scratch-nop"].get("verifier_counts") == oracle,
}
summary["checks"] = checks
summary["verdict"] = "PASS" if all(checks.values()) else "FAIL"
(run_dir / "summary.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
print(json.dumps({"verdict": summary["verdict"], "checks": checks}))
sys.exit(0 if summary["verdict"] == "PASS" else 1)
PY
date --iso-8601=seconds >"${RUN_DIR}/finished-at.txt"
