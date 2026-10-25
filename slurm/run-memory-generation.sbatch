#!/usr/bin/env bash
#SBATCH --job-name=fm-memory-offline-uv
#SBATCH --partition=batch
#SBATCH --gres=gpu:1
#SBATCH --cpus-per-task=4
#SBATCH --mem=48G
#SBATCH --time=12:00:00
#SBATCH --output=logs/memory-gen-%j.out
#SBATCH --error=logs/memory-gen-%j.err

set -euo pipefail
cd /home/csgrad/vbork001/frontiermemory-experiment-20261024

export PATH="${PWD}/bin:${PATH}"
export APPTAINER_CACHEDIR="${PWD}/containers/apptainer-cache"
export FM_BIND_EVIDENCE_SUMMARY=1
MODEL_STORE=/home/csgrad/vbork001/shared-mem-gov-pilot/models
SERVER_LOG="logs/ollama-memory-gen-${SLURM_JOB_ID}.log"

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
  if curl --fail --silent http://127.0.0.1:11434/api/tags >"results/ollama-tags-memory-gen-${SLURM_JOB_ID}.json"; then
    break
  fi
  sleep 2
done
test -s "results/ollama-tags-memory-gen-${SLURM_JOB_ID}.json"
apptainer exec --fakeroot \
  --bind "${MODEL_STORE}:/models" \
  --env OLLAMA_MODELS=/models \
  --env OLLAMA_HOST=127.0.0.1:11434 \
  containers/ollama.sif ollama pull qwen2.5-coder:7b
curl --fail --silent http://127.0.0.1:11434/api/tags >"results/ollama-tags-memory-gen-${SLURM_JOB_ID}.json"
grep -q 'qwen2.5-coder:7b' "results/ollama-tags-memory-gen-${SLURM_JOB_ID}.json"
nvidia-smi -L >"results/ollama-gpu-memory-gen-${SLURM_JOB_ID}.txt"

.venv/bin/harbor run \
  -p build/memory-task-v1.0 \
  --agent mini-swe-agent \
  --model ollama/qwen2.5-coder:7b \
  --env singularity \
  --jobs-dir jobs \
  --job-name frontiermemory-memory-qwen25coder7b-v1.0-command-evidence-v3 \
  --n-attempts 1 \
  --n-concurrent 1 \
  --agent-kwarg version=2.4.6 \
  --agent-kwarg config_file="${PWD}/configs/mini-swe-memory-ollama-7b.yaml" \
  --agent-env MSWEA_API_KEY=local-ollama-no-auth \
  --yes
