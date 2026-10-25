#!/usr/bin/env bash
#SBATCH --job-name=fm-memory-local-synthesis
#SBATCH --partition=batch
#SBATCH --gres=gpu:1
#SBATCH --cpus-per-task=4
#SBATCH --mem=32G
#SBATCH --time=02:00:00
#SBATCH --output=logs/direct-memory-%j.out
#SBATCH --error=logs/direct-memory-%j.err

set -euo pipefail
cd /home/csgrad/vbork001/frontiermemory-experiment-20261024

MODEL_STORE=/home/csgrad/vbork001/shared-mem-gov-pilot/models
SERVER_LOG="logs/ollama-direct-memory-${SLURM_JOB_ID}.log"
MEMORY_DIR="results/memory-generation-${SLURM_JOB_ID}"
mkdir -p "${MEMORY_DIR}/memory" "${MEMORY_DIR}/run"

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
  if curl --fail --silent http://127.0.0.1:11434/api/tags >"${MEMORY_DIR}/run/ollama-tags.json"; then
    break
  fi
  sleep 2
done
test -s "${MEMORY_DIR}/run/ollama-tags.json"
apptainer exec --fakeroot \
  --bind "${MODEL_STORE}:/models" \
  --env OLLAMA_MODELS=/models \
  --env OLLAMA_HOST=127.0.0.1:11434 \
  containers/ollama.sif ollama pull qwen2.5-coder:7b
nvidia-smi -L >"${MEMORY_DIR}/run/gpu.txt"

python3 scripts/generate_memory_from_evidence.py \
  data/evidence-summary.md \
  "${MEMORY_DIR}/memory/MEMORY.md" \
  "${MEMORY_DIR}/run/metrics.json"
.venv/bin/frontier-memory check-memory "${MEMORY_DIR}/memory" >"${MEMORY_DIR}/run/format-check.json"
