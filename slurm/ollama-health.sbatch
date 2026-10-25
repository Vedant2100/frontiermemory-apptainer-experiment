#!/usr/bin/env bash
#SBATCH --job-name=fm-ollama-health
#SBATCH --partition=gpu
#SBATCH --gres=gpu:1
#SBATCH --time=00:10:00
#SBATCH --mem=8G
#SBATCH --output=logs/ollama-health-%j.out
#SBATCH --error=logs/ollama-health-%j.err

set -euo pipefail
cd /home/csgrad/vbork001/frontiermemory-experiment-20261024

MODEL_STORE=/home/csgrad/vbork001/shared-mem-gov-pilot/models
SERVER_LOG="logs/ollama-server-${SLURM_JOB_ID}.log"

apptainer exec --fakeroot --nv \
  --bind "${MODEL_STORE}:/models" \
  --env OLLAMA_MODELS=/models \
  --env OLLAMA_HOST=127.0.0.1:11434 \
  --env OLLAMA_CONTEXT_LENGTH=32768 \
  containers/ollama.sif ollama serve >"${SERVER_LOG}" 2>&1 &
SERVER_PID=$!
cleanup() {
  kill "${SERVER_PID}" 2>/dev/null || true
  wait "${SERVER_PID}" 2>/dev/null || true
}
trap cleanup EXIT

for attempt in $(seq 1 60); do
  if curl --fail --silent http://127.0.0.1:11434/api/tags >"results/ollama-tags-${SLURM_JOB_ID}.json"; then
    break
  fi
  sleep 2
done
test -s "results/ollama-tags-${SLURM_JOB_ID}.json"
grep -q 'qwen2.5-coder:14b' "results/ollama-tags-${SLURM_JOB_ID}.json"
nvidia-smi -L >"results/ollama-gpu-${SLURM_JOB_ID}.txt"
cat "results/ollama-tags-${SLURM_JOB_ID}.json"
cat "results/ollama-gpu-${SLURM_JOB_ID}.txt"
