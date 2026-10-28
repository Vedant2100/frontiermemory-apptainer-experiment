#!/usr/bin/env bash
#SBATCH --job-name=fm-word2vec-oracle-check
#SBATCH --partition=batch
#SBATCH --cpus-per-task=4
#SBATCH --mem=16G
#SBATCH --time=01:30:00
#SBATCH --output=logs/word2vec-oracle-check-%j.out
#SBATCH --error=logs/word2vec-oracle-check-%j.err
# Same as check-word2vec-oracle-collection.sbatch, but Harbor runs through
# scripts/harbor_singularity_exec_timeout.py (exec-timeout correction, protocol-v2.md amendment 2026-10-27).
# CPU-only end-to-end collection check. Runs Harbor's built-in `oracle` agent (reference
# solution) and `nop` agent (no-op) through the same Apptainer task/verifier path as the
# OpenHands runner, without any model, Ollama, or GPU.
set -euo pipefail
cd /home/csgrad/vbork001/frontiermemory-experiment-20261024
export PATH="${PWD}/bin:${PATH}"
export APPTAINER_CACHEDIR="${PWD}/containers/apptainer-cache"

SOURCE_TASK="${PWD}/data/tasks/frontier-memory/build-word2vec-pipeline"
AGENT_SIF="${PWD}/containers/frontier-memory-word2vec-agent.sif"
VERIFIER_SIF="${PWD}/containers/frontier-memory-word2vec-verifier-harbor-py310.sif"
VERIFIER_DEF="${PWD}/containers/frontier-memory-word2vec-verifier-harbor.def"
VENV_SOURCE="${PWD}/runtime/openhands-sdk-venv"
PYTHON_SOURCE="${PWD}/runtime/uv/python/cpython-3.12-linux-x86_64-gnu"
HARBOR_SHARED_BINDPATH="${PYTHON_SOURCE}:${PYTHON_SOURCE},${VENV_SOURCE}:/opt/harbor-server"
HARBOR_WRAPPER="${PWD}/scripts/harbor_singularity_exec_timeout.py"
export HARBOR_SINGULARITY_EXEC_TIMEOUT_SEC="${HARBOR_SINGULARITY_EXEC_TIMEOUT_SEC:-7200}"
RUN_DIR="${PWD}/results/word2vec-openhands/oracle-check-${SLURM_JOB_ID}"
BUILD_ROOT="${PWD}/build/word2vec-apptainer/oracle-check/job-${SLURM_JOB_ID}"
HARBOR_BASE_NAME="frontiermemory-word2vec-oracle-check-${SLURM_JOB_ID}"

# Refuse to build or download anything: every image must already exist.
test -s "${AGENT_SIF}" && test -s "${VERIFIER_SIF}" && test -s "${VERIFIER_DEF}" && test -d "${SOURCE_TASK}" && test -s "${HARBOR_WRAPPER}"
test -x "${VENV_SOURCE}/bin/python" && test -x "${PYTHON_SOURCE}/bin/python3.12"
mkdir -p "${RUN_DIR}" "${BUILD_ROOT}" logs
date --iso-8601=seconds >"${RUN_DIR}/started-at.txt"
scontrol show job "${SLURM_JOB_ID}" >"${RUN_DIR}/slurm-job.txt"
.venv/bin/harbor --version >"${RUN_DIR}/harbor-version.txt"
sha256sum "${HARBOR_WRAPPER}" >"${RUN_DIR}/harbor-wrapper-sha256.txt"
printf 'HARBOR_SINGULARITY_EXEC_TIMEOUT_SEC=%s\n' "${HARBOR_SINGULARITY_EXEC_TIMEOUT_SEC}" >"${RUN_DIR}/harbor-exec-timeout.txt"
apptainer version >"${RUN_DIR}/apptainer-version.txt"
sha256sum "${SOURCE_TASK}/task.toml" "${SOURCE_TASK}/tests/Dockerfile" "${SOURCE_TASK}/tests/test.sh" "${SOURCE_TASK}/tests/test_outputs.py" >"${RUN_DIR}/official-task-verifier-sha256.txt"

# Verifier image preflight: the same checks as the Ada runner (Python 3.10 with test deps, pinned test-file hashes, Harbor server runtime).
sha256sum "${SOURCE_TASK}/tests/test.sh" "${SOURCE_TASK}/tests/test_outputs.py" >"${RUN_DIR}/verifier-source-sha256.txt"
apptainer exec --fakeroot --pwd /tests "${VERIFIER_SIF}" /bin/bash -lc 'test -s /tests/test.sh && test -s /tests/test_outputs.py && /usr/bin/python3 -c "import sys,gensim,nltk,numpy,pytest,scipy; assert sys.version_info[:2] == (3,10), sys.version; print(\"verifier-python\",sys.version.split()[0])"' >"${RUN_DIR}/verifier-image-preflight.txt" 2>&1
apptainer exec --fakeroot --pwd /tests "${VERIFIER_SIF}" sha256sum /tests/test.sh /tests/test_outputs.py >"${RUN_DIR}/verifier-image-tests-sha256.txt"
.venv/bin/python - "${RUN_DIR}/verifier-source-sha256.txt" "${RUN_DIR}/verifier-image-tests-sha256.txt" <<'PY'
import pathlib, sys
source, image = (pathlib.Path(path) for path in sys.argv[1:])
source_hashes = [line.split()[0] for line in source.read_text().splitlines()]
image_hashes = [line.split()[0] for line in image.read_text().splitlines()]
if source_hashes != image_hashes or len(source_hashes) != 2:
    raise SystemExit("Verifier SIF test files differ from the pinned task source")
PY
printf '%s\n' "${HARBOR_SHARED_BINDPATH}" >"${RUN_DIR}/apptainer-shared-bindpath.txt"
APPTAINER_BINDPATH="${HARBOR_SHARED_BINDPATH}" SINGULARITY_BINDPATH="${HARBOR_SHARED_BINDPATH}" apptainer exec --no-mount home,tmp,bind-paths --pwd /tests --writable-tmpfs --fakeroot --containall --pid "${VERIFIER_SIF}" /bin/bash -c '/usr/bin/python3 -c "import sys,gensim,nltk,numpy,pytest,scipy; assert sys.version_info[:2] == (3,10), sys.version; print(\"verifier-python\",sys.version.split()[0])" && /opt/harbor-server/bin/python3 -c "import fastapi,uvicorn; print(\"harbor-server-runtime\",fastapi.__version__,uvicorn.__version__)"' >"${RUN_DIR}/verifier-runtime-preflight.txt" 2>&1
sha256sum "${VERIFIER_SIF}" >"${RUN_DIR}/verifier-image-sha256.txt"
# Agent-side Python 3.12 + Harbor server runtime preflight (no OpenHands model work).
apptainer exec --fakeroot --writable-tmpfs --containall --no-mount home,tmp,bind-paths --bind "${PYTHON_SOURCE}/bin/python3.12:/usr/bin/python3" --pwd /workspace "${AGENT_SIF}" /bin/bash -c '/usr/bin/python3 --version' >"${RUN_DIR}/agent-runtime-preflight.txt" 2>&1

run_trial() {
  local name="$1" agent="$2"
  local task_path="${BUILD_ROOT}/${name}/build-word2vec-pipeline"
  local workspace="${RUN_DIR}/${name}/workspace"
  local job_name="${HARBOR_BASE_NAME}-${name}"
  mkdir -p "${RUN_DIR}/${name}" "${workspace}"
  chmod 777 "${workspace}"
  date --iso-8601=seconds >"${RUN_DIR}/${name}/started-at.txt"

  # Fresh staged task copy for this trial, using the same staging helper as the runner.
  .venv/bin/python scripts/stage_word2vec_task_for_apptainer.py --source "${SOURCE_TASK}" --output "${task_path}" --agent-image "${AGENT_SIF}" --verifier-image "${VERIFIER_SIF}" >"${RUN_DIR}/${name}/task-staging.json"
  .venv/bin/python - "${task_path}/task.toml" "${RUN_DIR}/${name}/task-staging.json" "${RUN_DIR}/${name}/staged-task-preflight.json" <<'PY'
import json, pathlib, sys, tomllib
task_path, staging_path, output_path = map(pathlib.Path, sys.argv[1:])
task = tomllib.loads(task_path.read_text(encoding="utf-8"))
staging = json.loads(staging_path.read_text(encoding="utf-8"))
verifier = task["verifier"]["environment"]
if verifier.get("network_mode") != "public":
    raise SystemExit("Apptainer preflight: verifier network_mode must be staged as public")
if staging.get("network_egress_isolation_enforced") is not False:
    raise SystemExit("Apptainer preflight: missing explicit network-isolation limitation")
artifacts = task.get("artifacts", [])
if not artifacts or any(not isinstance(p, str) or not p.startswith("/workspace/") for p in artifacts):
    raise SystemExit(f"Unexpected or missing artifact metadata: {artifacts!r}")
summary = {
    "task": task["task"]["name"],
    "declared_artifacts": artifacts,
    "verifier_network_mode": verifier["network_mode"],
    "network_egress_isolation_enforced": False,
    "verifier_tests_embedded_in_separate_verifier_image": True,
    "preflight": "passed",
}
output_path.write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
PY
  local mounts_json
  mounts_json="$(.venv/bin/python -c 'import json,sys; p,w=sys.argv[1:]; print(json.dumps([{"type":"bind","source":p+"/bin/python3.12","target":"/usr/bin/python3"},{"type":"bind","source":w,"target":"/workspace"}]))' "${PYTHON_SOURCE}" "${workspace}")"
  printf '%s\n' "${mounts_json}" >"${RUN_DIR}/${name}/environment-mounts.json"
  local common_args=(--path "${task_path}" --env singularity --mounts-json "${mounts_json}" --jobs-dir jobs --job-name "${job_name}" --agent "${agent}" --n-attempts 1 --n-concurrent 1 --agent-timeout-multiplier 1.0 --agent-setup-timeout-multiplier 0.5 --yes)
  APPTAINER_BINDPATH="${HARBOR_SHARED_BINDPATH}" SINGULARITY_BINDPATH="${HARBOR_SHARED_BINDPATH}" .venv/bin/python "${HARBOR_WRAPPER}" run "${common_args[@]}" --print-config >"${RUN_DIR}/${name}/harbor-resolved-config.json" 2>"${RUN_DIR}/${name}/harbor-config.log" || true
  set +e
  APPTAINER_BINDPATH="${HARBOR_SHARED_BINDPATH}" SINGULARITY_BINDPATH="${HARBOR_SHARED_BINDPATH}" timeout --signal=INT --kill-after=20s 1800s .venv/bin/python "${HARBOR_WRAPPER}" run "${common_args[@]}" >"${RUN_DIR}/${name}/harbor.log" 2>&1
  local exit_code=$?
  set -e
  printf '%s\n' "${exit_code}" >"${RUN_DIR}/${name}/harbor-exit-code.txt"
  if test -s "${workspace}/solution.py"; then echo present >"${RUN_DIR}/${name}/solution-artifact.txt"; else echo absent >"${RUN_DIR}/${name}/solution-artifact.txt"; fi
  if [[ -d "jobs/${job_name}" ]]; then
    local trial_dir
    trial_dir="$(find "jobs/${job_name}" -mindepth 1 -maxdepth 1 -type d | head -n 1)"
    if [[ -n "${trial_dir}" ]]; then printf '%s\n' "${trial_dir}" >"${RUN_DIR}/${name}/harbor-source-dir.txt"; cp -a "${trial_dir}" "${RUN_DIR}/${name}/harbor-trial"; fi
  fi
  date --iso-8601=seconds >"${RUN_DIR}/${name}/finished-at.txt"
  # Sanity: the workspace bind is fresh for this trial, so any artifact here came from this agent only.
  echo "${name} agent=${agent} harbor_exit=${exit_code}"
}

run_trial oracle oracle || true
run_trial nop nop || true
date --iso-8601=seconds >"${RUN_DIR}/finished-at.txt"
