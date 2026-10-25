#!/usr/bin/env bash
#SBATCH --job-name=fm-awilix-terminus2
#SBATCH --partition=batch
#SBATCH --constraint=rtx2080ti
#SBATCH --gres=gpu:1
#SBATCH --cpus-per-task=4
#SBATCH --mem=48G
#SBATCH --time=01:30:00
#SBATCH --output=logs/terminus2-awilix-%j.out
#SBATCH --error=logs/terminus2-awilix-%j.err

set -euo pipefail
cd /home/csgrad/vbork001/frontiermemory-experiment-20261024

export PATH="${PWD}/bin:${PATH}"
export APPTAINER_CACHEDIR="${PWD}/containers/apptainer-cache"
unset FM_BIND_EVIDENCE_SUMMARY || true

MODEL_STORE=/home/csgrad/vbork001/shared-mem-gov-pilot/models
SERVER_LOG="logs/ollama-terminus2-${SLURM_JOB_ID}.log"
RESULT_FILE="results/terminus2-awilix-${SLURM_JOB_ID}-status.txt"
mkdir -p logs results

# Use the already staged task and the same original verifier SIF as the prior
# Mini-SWE run. The official benchmark files remain untouched.
apptainer exec --fakeroot \
  containers/awilix-release-tier-implicit-verifier.sif \
  /bin/sh -c 'test -x /tests/test.sh && /opt/harbor-server/bin/python -c "import fastapi, uvicorn"'

apptainer exec --fakeroot --nv \
  --bind "${MODEL_STORE}:/models" \
  --env OLLAMA_MODELS=/models \
  --env OLLAMA_HOST=127.0.0.1:11434 \
  --env OLLAMA_CONTEXT_LENGTH=8192 \
  containers/ollama.sif ollama serve >"${SERVER_LOG}" 2>&1 &
SERVER_PID=$!
cleanup() {
  kill "${SERVER_PID}" 2>/dev/null || true
  wait "${SERVER_PID}" 2>/dev/null || true
}
trap cleanup EXIT

for attempt in $(seq 1 60); do
  if curl --fail --silent http://127.0.0.1:11434/api/tags >"results/ollama-tags-terminus2-${SLURM_JOB_ID}.json"; then
    break
  fi
  sleep 2
done
test -s "results/ollama-tags-terminus2-${SLURM_JOB_ID}.json"

# This tag is already present in the persistent model store from the earlier
# Mini-SWE pilot; pull is a no-op when the local manifest and layers exist.
apptainer exec --fakeroot \
  --bind "${MODEL_STORE}:/models" \
  --env OLLAMA_MODELS=/models \
  --env OLLAMA_HOST=127.0.0.1:11434 \
  containers/ollama.sif ollama pull qwen2.5-coder:7b

curl --fail --silent http://127.0.0.1:11434/api/tags >"results/ollama-tags-terminus2-${SLURM_JOB_ID}.json"
nvidia-smi -L >"results/ollama-gpu-terminus2-${SLURM_JOB_ID}.txt"

set +e
.venv/bin/harbor run \
  --path build/awilix-release-tier-implicit-apptainer \
  --agent terminus-2 \
  --model ollama/qwen2.5-coder:7b \
  --env singularity \
  --config configs/terminus2-host-tmux.yaml \
  --jobs-dir jobs \
  --job-name frontiermemory-awilix-implicit-v1.0-qwen7b-terminus2-tmuxbind-diagnostic-no-memory \
  --n-attempts 1 \
  --n-concurrent 1 \
  --agent-kwarg api_base=http://127.0.0.1:11434 \
  --agent-kwarg max_turns=50 \
  --agent-kwarg record_terminal_session=false \
  --yes
HARBOR_EXIT=$?
set -e

printf 'Harbor process exit: %s\n' "${HARBOR_EXIT}" >"${RESULT_FILE}"
exit "${HARBOR_EXIT}"
