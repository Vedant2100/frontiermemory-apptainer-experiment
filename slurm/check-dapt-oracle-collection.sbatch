#!/usr/bin/env bash
#SBATCH --job-name=fm-dapt-oracle-check
#SBATCH --partition=batch
#SBATCH --cpus-per-task=4
#SBATCH --mem=16G
#SBATCH --time=02:00:00
#SBATCH --output=logs/dapt-oracle-check-%j.out
#SBATCH --error=logs/dapt-oracle-check-%j.err
# CPU-only end-to-end collection check for dapt-intrusion-detection-workflow-learning.
# Runs Harbor's built-in `oracle` agent (reference solution) and `nop` agent (no-op)
# through the Apptainer task/verifier path, via scripts/harbor_singularity_exec_timeout.py.
# No model, Ollama, or GPU. The task's declared artifact is /root/network_stats.csv
# (the agent's working directory is /root). Harbor downloads it from the agent
# container and re-uploads it into the separate verifier container at the same path,
# so no workspace bind mount is needed.
set -euo pipefail
cd /home/csgrad/vbork001/frontiermemory-experiment-20261024
export PATH="${PWD}/bin:${PATH}"
export APPTAINER_CACHEDIR="${PWD}/containers/apptainer-cache"

SOURCE_TASK="${PWD}/data/tasks/frontier-memory/dapt-intrusion-detection-workflow-learning"
AGENT_SIF="${PWD}/containers/frontier-memory-dapt-agent.sif"
VERIFIER_SIF="${PWD}/containers/frontier-memory-dapt-verifier-v2.sif"
VENV_SOURCE="${PWD}/runtime/openhands-sdk-venv"
PYTHON_SOURCE="${PWD}/runtime/uv/python/cpython-3.12-linux-x86_64-gnu"
# Same shared Harbor server runtime as the word2vec check: the venv's uvicorn/fastapi
# are bound at /opt/harbor-server so the in-container bootstrap needs no PyPI access.
HARBOR_SHARED_BINDPATH="${PYTHON_SOURCE}:${PYTHON_SOURCE},${VENV_SOURCE}:/opt/harbor-server"
HARBOR_WRAPPER="${PWD}/scripts/harbor_singularity_exec_timeout.py"
export HARBOR_SINGULARITY_EXEC_TIMEOUT_SEC="${HARBOR_SINGULARITY_EXEC_TIMEOUT_SEC:-7200}"
RUN_DIR="${PWD}/results/frontiermemory-dapt/oracle-check-${SLURM_JOB_ID}"
BUILD_ROOT="${PWD}/build/dapt-apptainer/oracle-check/job-${SLURM_JOB_ID}"
HARBOR_BASE_NAME="frontiermemory-dapt-oracle-check-${SLURM_JOB_ID}"

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
# Hash of the official task files (original, unmodified; hashing only, never reading tests/ or solution/).
(cd "${SOURCE_TASK}" && find . -type f -print0 | sort -z | xargs -0 sha256sum) >"${RUN_DIR}/official-task-sha256.txt"
sha256sum "${SOURCE_TASK}/tests/test.sh" "${SOURCE_TASK}/tests/test_outputs.py" >"${RUN_DIR}/verifier-source-sha256.txt"
sha256sum "${VERIFIER_SIF}" >"${RUN_DIR}/verifier-image-sha256.txt"

# Verifier image preflight: pinned test-file hashes, verifier Python dependencies, and Harbor server runtime.
apptainer exec --fakeroot --pwd /tests "${VERIFIER_SIF}" sha256sum /tests/test.sh /tests/test_outputs.py >"${RUN_DIR}/verifier-image-tests-sha256.txt"
.venv/bin/python - "${RUN_DIR}/verifier-source-sha256.txt" "${RUN_DIR}/verifier-image-tests-sha256.txt" <<'PY'
import pathlib, sys
source, image = (pathlib.Path(path) for path in sys.argv[1:])
source_hashes = [line.split()[0] for line in source.read_text().splitlines()]
image_hashes = [line.split()[0] for line in image.read_text().splitlines()]
if source_hashes != image_hashes or len(source_hashes) != 2:
    raise SystemExit("Verifier SIF test files differ from the pinned task source")
PY
apptainer exec --fakeroot --pwd /tests "${VERIFIER_SIF}" /bin/bash -lc 'test -s /tests/test.sh && test -s /tests/test_outputs.py && /usr/bin/python3 -c "import sys,pytest,scapy,pandas,numpy; print(\"verifier-python\",sys.version.split()[0],\"pytest\",pytest.__version__)"' >"${RUN_DIR}/verifier-image-preflight.txt" 2>&1
printf '%s\n' "${HARBOR_SHARED_BINDPATH}" >"${RUN_DIR}/apptainer-shared-bindpath.txt"
APPTAINER_BINDPATH="${HARBOR_SHARED_BINDPATH}" SINGULARITY_BINDPATH="${HARBOR_SHARED_BINDPATH}" apptainer exec --no-mount home,tmp,bind-paths --pwd /tests --writable-tmpfs --fakeroot --containall --pid "${VERIFIER_SIF}" /bin/bash -c '/opt/harbor-server/bin/python3 -c "import fastapi,uvicorn; print(\"harbor-server-runtime\",fastapi.__version__,uvicorn.__version__)"' >"${RUN_DIR}/verifier-runtime-preflight.txt" 2>&1
# Agent image preflight: the official environment packages and the declared input file.
apptainer exec --fakeroot --writable-tmpfs --containall --no-mount home,tmp,bind-paths --pwd /root "${AGENT_SIF}" /bin/bash -c 'test -s /root/packets.pcap && test -s /root/network_stats.csv && python3 -c "import scapy,pandas,numpy,sys; print(\"agent-python\",sys.version.split()[0])"' >"${RUN_DIR}/agent-runtime-preflight.txt" 2>&1

run_trial() {
  local name="$1" agent="$2"
  local task_path="${BUILD_ROOT}/${name}/dapt-intrusion-detection-workflow-learning"
  local job_name="${HARBOR_BASE_NAME}-${name}"
  mkdir -p "${RUN_DIR}/${name}"
  date --iso-8601=seconds >"${RUN_DIR}/${name}/started-at.txt"

  # Fresh staged task copy for this trial. The staging helper is generic (it only rewrites
  # docker_image and the verifier network mode in a copy of task.toml).
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
if artifacts != ["/root/network_stats.csv"]:
    raise SystemExit(f"Unexpected artifact metadata: {artifacts!r}")
summary = {
    "task": task["task"]["name"],
    "declared_artifacts": artifacts,
    "agent_timeout_sec": task["agent"]["timeout_sec"],
    "verifier_timeout_sec": verifier.get("timeout_sec", task["verifier"]["timeout_sec"]),
    "verifier_network_mode": verifier["network_mode"],
    "network_egress_isolation_enforced": False,
    "verifier_tests_embedded_in_separate_verifier_image": True,
    "preflight": "passed",
}
output_path.write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
PY
  # No workspace or extra mounts: the artifact lives at /root inside the agent container and Harbor transfers it.
  local common_args=(--path "${task_path}" --env singularity --mounts-json '[]' --jobs-dir jobs --job-name "${job_name}" --agent "${agent}" --n-attempts 1 --n-concurrent 1 --agent-timeout-multiplier 1.0 --agent-setup-timeout-multiplier 0.5 --yes)
  APPTAINER_BINDPATH="${HARBOR_SHARED_BINDPATH}" SINGULARITY_BINDPATH="${HARBOR_SHARED_BINDPATH}" .venv/bin/python "${HARBOR_WRAPPER}" run "${common_args[@]}" --print-config >"${RUN_DIR}/${name}/harbor-resolved-config.json" 2>"${RUN_DIR}/${name}/harbor-config.log" || true
  set +e
  APPTAINER_BINDPATH="${HARBOR_SHARED_BINDPATH}" SINGULARITY_BINDPATH="${HARBOR_SHARED_BINDPATH}" timeout --signal=INT --kill-after=20s 2700s .venv/bin/python "${HARBOR_WRAPPER}" run "${common_args[@]}" >"${RUN_DIR}/${name}/harbor.log" 2>&1
  local exit_code=$?
  set -e
  printf '%s\n' "${exit_code}" >"${RUN_DIR}/${name}/harbor-exit-code.txt"
  if [[ -d "jobs/${job_name}" ]]; then
    local trial_dir
    trial_dir="$(find "jobs/${job_name}" -mindepth 1 -maxdepth 1 -type d | head -n 1)"
    if [[ -n "${trial_dir}" ]]; then printf '%s\n' "${trial_dir}" >"${RUN_DIR}/${name}/harbor-source-dir.txt"; cp -a "${trial_dir}" "${RUN_DIR}/${name}/harbor-trial"; fi
  fi
  date --iso-8601=seconds >"${RUN_DIR}/${name}/finished-at.txt"
  echo "${name} agent=${agent} harbor_exit=${exit_code}"
}

run_trial oracle oracle || true
run_trial nop nop || true
date --iso-8601=seconds >"${RUN_DIR}/finished-at.txt"
