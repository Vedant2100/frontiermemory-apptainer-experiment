#!/usr/bin/env bash
#SBATCH --job-name=fm-awilix-ab-local
#SBATCH --partition=batch
#SBATCH --gres=gpu:1
#SBATCH --cpus-per-task=4
#SBATCH --mem=48G
#SBATCH --time=04:00:00
#SBATCH --output=logs/awilix-ab-%j.out
#SBATCH --error=logs/awilix-ab-%j.err

set -euo pipefail
cd /home/csgrad/vbork001/frontiermemory-experiment-20261024

export PATH="${PWD}/bin:${PATH}"
export APPTAINER_CACHEDIR="${PWD}/containers/apptainer-cache"
unset FM_BIND_EVIDENCE_SUMMARY || true
MODEL_STORE=/home/csgrad/vbork001/shared-mem-gov-pilot/models
SERVER_LOG="logs/ollama-awilix-ab-${SLURM_JOB_ID}.log"
RUN_EXIT_FILE="results/awilix-ab-${SLURM_JOB_ID}-harbor-exits.txt"
mkdir -p results

# Fail before loading the GPU model if Harbor's separate verifier runtime is
# missing either the original test entry point or its local FastAPI service.
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
  if curl --fail --silent http://127.0.0.1:11434/api/tags >"results/ollama-tags-awilix-ab-${SLURM_JOB_ID}.json"; then
    break
  fi
  sleep 2
done
test -s "results/ollama-tags-awilix-ab-${SLURM_JOB_ID}.json"
apptainer exec --fakeroot \
  --bind "${MODEL_STORE}:/models" \
  --env OLLAMA_MODELS=/models \
  --env OLLAMA_HOST=127.0.0.1:11434 \
  containers/ollama.sif ollama pull qwen2.5-coder:7b
curl --fail --silent http://127.0.0.1:11434/api/tags >"results/ollama-tags-awilix-ab-${SLURM_JOB_ID}.json"
nvidia-smi -L >"results/ollama-gpu-awilix-ab-${SLURM_JOB_ID}.txt"

set +e
.venv/bin/harbor run \
  --path build/awilix-release-tier-implicit-apptainer \
  --agent mini-swe-agent \
  --model ollama/qwen2.5-coder:7b \
  --env singularity \
  --jobs-dir jobs \
  --job-name frontiermemory-awilix-implicit-v1.0-qwen7b-A-no-memory-publicnet-step50-verifiersif \
  --n-attempts 1 \
  --n-concurrent 1 \
  --agent-kwarg version=2.4.6 \
  --agent-kwarg config_file="${PWD}/configs/mini-swe-ollama-7b.yaml" \
  --agent-env MSWEA_API_KEY=local-ollama-no-auth \
  --yes
A_EXIT=$?

.venv/bin/harbor run \
  --path build/awilix-release-tier-implicit-apptainer \
  --agent mini-swe-agent \
  --model ollama/qwen2.5-coder:7b \
  --env singularity \
  --jobs-dir jobs \
  --job-name frontiermemory-awilix-implicit-v1.0-qwen7b-B-learned-memory-publicnet-step50-verifiersif \
  --n-attempts 1 \
  --n-concurrent 1 \
  --agent-kwarg version=2.4.6 \
  --agent-kwarg config_file="${PWD}/configs/mini-swe-ollama-7b-memory.yaml" \
  --agent-env MSWEA_API_KEY=local-ollama-no-auth \
  --yes
B_EXIT=$?
set -e

printf 'A Harbor process exit: %s\nB Harbor process exit: %s\n' "${A_EXIT}" "${B_EXIT}" >"${RUN_EXIT_FILE}"
if [[ "${A_EXIT}" -ne 0 || "${B_EXIT}" -ne 0 ]]; then
  exit 1
fi
