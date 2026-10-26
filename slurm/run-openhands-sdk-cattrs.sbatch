#!/usr/bin/env bash
#SBATCH --job-name=fm-openhands-cattrs-qwen38
#SBATCH --partition=vcggpu
#SBATCH --constraint=rtx3090
#SBATCH --gres=gpu:1
#SBATCH --cpus-per-task=8
#SBATCH --mem=48G
#SBATCH --time=00:35:00
#SBATCH --output=logs/openhands-sdk-cattrs-%j.out
#SBATCH --error=logs/openhands-sdk-cattrs-%j.err

set -euo pipefail
cd /home/csgrad/vbork001/frontiermemory-experiment-20261024

export PATH="${PWD}/bin:${PATH}"
export APPTAINER_CACHEDIR="${PWD}/containers/apptainer-cache"
export OLLAMA_CONTEXT_LENGTH=32768
export OLLAMA_KEEP_ALIVE=20m
export OLLAMA_HOST=127.0.0.1:11434
export OLLAMA_MODELS=/models

MODEL="qwen3.8:27b-mtp-q4_K_M"
MODEL_API_NAME="openai/${MODEL}"
MODEL_STORE="/home/csgrad/vbork001/shared-mem-gov-pilot/models"
OLLAMA_SIF="${PWD}/containers/ollama.sif"
TASK_PATH="${TASK_PATH:-${PWD}/build/opencode-frontiermemory-tasks/cattrs-compositional-changelog}"
TASK_IMAGE="${TASK_IMAGE:-${PWD}/containers/frontier-memory-cattrs.sif}"
PROMPT_TEMPLATE="${OPENHANDS_PROMPT_TEMPLATE:?Pass the no-memory prompt template from the OpenCode run}"
RUN_DIR="${PWD}/results/openhands-sdk-frontiermemory/job-${SLURM_JOB_ID}"
HARBOR_JOB_NAME="frontiermemory-v1.0-cattrs-compositional-changelog-openhands-sdk-${MODEL//:/-}-A-${SLURM_JOB_ID}"

test -s "${PROMPT_TEMPLATE}"
test -d "${MODEL_STORE}"
test -f "${OLLAMA_SIF}"
test -f "${TASK_IMAGE}"
test -f "${TASK_PATH}/task.toml"
mkdir -p "${RUN_DIR}/ollama"
date --iso-8601=seconds >"${RUN_DIR}/started-at.txt"
scontrol show job "${SLURM_JOB_ID}" >"${RUN_DIR}/slurm-job.txt"
nvidia-smi -q >"${RUN_DIR}/nvidia-smi.txt"
nvidia-smi --query-gpu=name,memory.total,memory.free --format=csv >"${RUN_DIR}/gpu.csv"
grep -Eq 'GeForce RTX 3090' "${RUN_DIR}/gpu.csv"
.venv/bin/harbor --version >"${RUN_DIR}/harbor-version.txt"
apptainer version >"${RUN_DIR}/apptainer-version.txt"
runtime/uv/bin/uv pip freeze --python runtime/openhands-sdk-venv/bin/python \
  >"${RUN_DIR}/openhands-sdk-freeze.txt"
singularity exec --fakeroot "${TASK_IMAGE}" \
  /opt/openhands-sdk-venv/bin/python -c \
  'import openhands.sdk, openhands.tools, fastapi; print("openhands-sdk", openhands.sdk.__version__); print("fastapi", fastapi.__version__)' \
  >"${RUN_DIR}/openhands-apptainer-preflight.txt"
apptainer exec --fakeroot "${OLLAMA_SIF}" ollama --version >"${RUN_DIR}/ollama-version.txt" 2>&1
printf '%s\n' "${MODEL}" >"${RUN_DIR}/model.txt"
printf '%s\n' "${PROMPT_TEMPLATE}" >"${RUN_DIR}/prompt-template-path.txt"

apptainer exec --fakeroot --nv \
  --bind "${MODEL_STORE}:/models" \
  --env OLLAMA_MODELS=/models \
  --env OLLAMA_HOST=127.0.0.1:11434 \
  --env OLLAMA_CONTEXT_LENGTH="${OLLAMA_CONTEXT_LENGTH}" \
  --env OLLAMA_KEEP_ALIVE="${OLLAMA_KEEP_ALIVE}" \
  "${OLLAMA_SIF}" ollama serve >"${RUN_DIR}/ollama/server.log" 2>&1 &
SERVER_PID=$!
cleanup() {
  if [[ -n "${SERVER_PID:-}" ]]; then
    kill "${SERVER_PID}" 2>/dev/null || true
    wait "${SERVER_PID}" 2>/dev/null || true
  fi
  date --iso-8601=seconds >"${RUN_DIR}/finished-at.txt"
}
trap cleanup EXIT

READY=0
for attempt in $(seq 1 60); do
  if curl --fail --silent http://127.0.0.1:11434/api/version >"${RUN_DIR}/ollama/api-version.json"; then
    READY=1
    break
  fi
  sleep 2
done
test "${READY}" = 1
curl --fail --silent http://127.0.0.1:11434/api/tags >"${RUN_DIR}/ollama/tags.json"
grep -q "${MODEL}" "${RUN_DIR}/ollama/tags.json"
.venv/bin/python scripts/probe_ollama_thinking.py \
  --model "${MODEL}" \
  --output-dir "${RUN_DIR}/ollama/thinking-probe"
curl --fail --silent http://127.0.0.1:11434/api/ps >"${RUN_DIR}/ollama/loaded-model-before-agent.json"

set +e
timeout --signal=INT --kill-after=15s 900s .venv/bin/harbor run \
  --path "${TASK_PATH}" \
  --env singularity \
  --jobs-dir jobs \
  --job-name "${HARBOR_JOB_NAME}" \
  --agent openhands-sdk \
  --model "${MODEL_API_NAME}" \
  --agent-kwarg "prompt_template_path=${PROMPT_TEMPLATE}" \
  --agent-kwarg "reasoning_effort=none" \
  --agent-kwarg "temperature=1.0" \
  --agent-kwarg "load_skills=false" \
  --agent-kwarg "max_iterations=8" \
  --agent-env "LLM_API_KEY=local-ollama-no-auth" \
  --agent-env "LLM_BASE_URL=http://127.0.0.1:11434/v1" \
  --n-attempts 1 \
  --n-concurrent 1 \
  --agent-timeout-multiplier 1.0 \
  --agent-setup-timeout-multiplier 0.5 \
  --yes >"${RUN_DIR}/harbor.log" 2>&1
HARBOR_EXIT=$?
set -e
printf '%s\n' "${HARBOR_EXIT}" >"${RUN_DIR}/harbor-exit-code.txt"
curl --fail --silent http://127.0.0.1:11434/api/ps >"${RUN_DIR}/ollama/loaded-model-after-agent.json" || true

TRIAL_DIR=""
if [[ -d "jobs/${HARBOR_JOB_NAME}" ]]; then
  TRIAL_DIR="$(find "jobs/${HARBOR_JOB_NAME}" -mindepth 1 -maxdepth 1 -type d | head -n 1)"
fi
if [[ -n "${TRIAL_DIR}" ]]; then
  printf '%s\n' "${TRIAL_DIR}" >"${RUN_DIR}/harbor-source-dir.txt"
  for relative in agent/trajectory.json agent/openhands_sdk.txt artifacts/logs/artifacts/model.patch \
    artifacts/manifest.json verifier/reward.txt verifier/reward.json result.json exception.txt config.json lock.json trial.log; do
    if [[ -f "${TRIAL_DIR}/${relative}" ]]; then
      mkdir -p "${RUN_DIR}/harbor/$(dirname "${relative}")"
      cp "${TRIAL_DIR}/${relative}" "${RUN_DIR}/harbor/${relative}"
    fi
  done
fi
date --iso-8601=seconds >"${RUN_DIR}/run-body-finished-at.txt"
exit "${HARBOR_EXIT}"
