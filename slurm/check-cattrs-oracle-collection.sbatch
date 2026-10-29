#!/usr/bin/env bash
#SBATCH --job-name=fm-cattrs-oracle-check
#SBATCH --partition=batch
#SBATCH --cpus-per-task=4
#SBATCH --mem=16G
#SBATCH --time=03:00:00
#SBATCH --output=logs/cattrs-oracle-check-%j.out
#SBATCH --error=logs/cattrs-oracle-check-%j.err
# CPU-only grading check for cattrs-compositional-changelog (patch artifact). No model, Ollama, or GPU.
#   nop          Harbor's nop agent on the unmodified base repository. The task's collect step yields an empty
#                patch. Expect reward 0.
#   oracle       Harbor's oracle agent runs the task's reference solution in its agent container, as the DAPT
#                oracle check does. Expect reward 1 and every case passing.
#   scratch-nop  The reference solution applied to a scratch copy of the repository and committed, then collected
#                with the task's collect command. Graded by the nop agent with that copy bound at /app, which is the
#                patch-task grading path of scripts/run_codex_ollama_trial.sh. Expect reward 1.
# Only counts, sizes, and hashes go into the run directory (gitignored). Verifier output, patches, and the solution
# text stay in Harbor's jobs/ directory and in build/ (both gitignored) and are not printed or copied.
set -euo pipefail
cd /home/csgrad/vbork001/frontiermemory-experiment-20261024
export PATH="${PWD}/bin:${PATH}"
export APPTAINER_CACHEDIR="${PWD}/containers/apptainer-cache"
PY="${PWD}/.venv/bin/python"

TASK_NAME=cattrs-compositional-changelog
SOURCE_TASK="${PWD}/data/tasks/frontier-memory/${TASK_NAME}"
AGENT_SIF="${PWD}/containers/frontier-memory-cattrs.sif"
VERIFIER_SIF="${PWD}/containers/frontier-memory-cattrs-verifier.sif"
VENV_SOURCE="${PWD}/runtime/openhands-sdk-venv"
PYTHON_SOURCE="${PWD}/runtime/uv/python/cpython-3.12-linux-x86_64-gnu"
# Same shared Harbor server runtime as the DAPT oracle check.
HARBOR_SHARED_BINDPATH="${PYTHON_SOURCE}:${PYTHON_SOURCE},${VENV_SOURCE}:/opt/harbor-server"
HARBOR_WRAPPER="${PWD}/scripts/harbor_singularity_exec_timeout.py"
export HARBOR_SINGULARITY_EXEC_TIMEOUT_SEC="${HARBOR_SINGULARITY_EXEC_TIMEOUT_SEC:-7200}"
RUN_DIR="${PWD}/results/cattrs-oracle-check-${SLURM_JOB_ID}"
BUILD_ROOT="${PWD}/build/cattrs-apptainer/oracle-check/job-${SLURM_JOB_ID}"
HARBOR_BASE_NAME="frontiermemory-cattrs-oracle-check-${SLURM_JOB_ID}"
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

# Agent image: the repository must sit at the task base commit, and the cattrs package must import.
BASE_COMMIT="$("${PY}" -c 'import sys,tomllib; print(tomllib.load(open(sys.argv[1],"rb"))["metadata"]["base_commit_hash"])' "${SOURCE_TASK}/task.toml")"
COLLECT_COMMAND="$("${PY}" -c 'import sys,tomllib; print(tomllib.load(open(sys.argv[1],"rb"))["verifier"]["collect"][0]["command"])' "${SOURCE_TASK}/task.toml")"
apptainer exec --fakeroot --writable-tmpfs --containall --no-mount home,tmp,bind-paths --pwd /app "${AGENT_SIF}" /bin/bash -c \
  'git -C /app rev-parse HEAD && python3 -c "import cattrs,sys; print(\"agent-python\", sys.version.split()[0])"' \
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

# Counts, sizes, and hashes only. The collected patches are hashed, never printed.
local_patch="${SCRATCH_DIR}/logs/artifacts/model.patch"
"${PY}" - "${RUN_DIR}" "${JOBS_DIR}" "${HARBOR_BASE_NAME}" "${local_patch}" <<'PY'
import hashlib, json, sys
from pathlib import Path

run_dir, jobs_dir, base, local_patch = Path(sys.argv[1]), Path(sys.argv[2]), sys.argv[3], Path(sys.argv[4])

def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else None

def trial(name):
    job = jobs_dir / f"{base}-{name}"
    dirs = sorted(p for p in job.glob("*") if p.is_dir()) if job.is_dir() else []
    if not dirs:
        return {"harbor_trial_found": False}
    t = dirs[0]
    result = json.loads((t / "result.json").read_text()) if (t / "result.json").is_file() else {}
    rj = json.loads((t / "verifier" / "reward.json").read_text()) if (t / "verifier" / "reward.json").is_file() else {}
    patch = t / "artifacts" / "logs" / "artifacts" / "model.patch"
    reward = ((result.get("verifier_result") or {}).get("rewards") or {}).get("reward", rj.get("reward"))
    exc = (result.get("exception_info") or {}).get("exception_type")
    counts = {k: rj.get(k) for k in ("f2p_total", "f2p_passed", "p2p_total", "p2p_passed")}
    total = sum(v or 0 for k, v in counts.items() if k.endswith("_total"))
    passed = sum(v or 0 for k, v in counts.items() if k.endswith("_passed"))
    return {
        "harbor_trial_found": True, "reward": reward, "exception_type": exc,
        "verifier_reward_json_present": bool(rj), "counts": counts, "cases_total": total, "cases_passed": passed,
        "collected_patch_bytes": patch.stat().st_size if patch.is_file() else None,
        "collected_patch_sha256": sha(patch),
    }

summary = {name: trial(name) for name in ("nop", "oracle", "scratch-nop")}
summary["local_scratch_collect_exit"] = int((run_dir / "scratch-collect-exit.txt").read_text().strip() or -1)
summary["local_scratch_patch_bytes"] = local_patch.stat().st_size if local_patch.is_file() else None
summary["local_scratch_patch_sha256"] = sha(local_patch)
checks = {
    "nop_reward_0_empty_patch": summary["nop"].get("reward") == 0 and summary["nop"].get("collected_patch_bytes") == 0,
    "oracle_reward_1_all_cases": summary["oracle"].get("reward") == 1
        and summary["oracle"].get("cases_total", 0) > 0
        and summary["oracle"].get("cases_passed") == summary["oracle"].get("cases_total"),
    "scratch_reward_1": summary["scratch-nop"].get("reward") == 1,
    "scratch_collected_matches_local": summary["local_scratch_patch_sha256"] is not None
        and summary["scratch-nop"].get("collected_patch_sha256") == summary["local_scratch_patch_sha256"],
    "cases_total_from_oracle_is_77": summary["oracle"].get("cases_total") == 77,
}
summary["checks"] = checks
summary["verdict"] = "PASS" if all(checks.values()) else "FAIL"
(run_dir / "summary.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
print(json.dumps({"verdict": summary["verdict"], "checks": checks}))
sys.exit(0 if summary["verdict"] == "PASS" else 1)
PY
date --iso-8601=seconds >"${RUN_DIR}/finished-at.txt"
