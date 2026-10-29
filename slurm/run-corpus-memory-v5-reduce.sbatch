#!/usr/bin/env bash
# Memory v5 reduce: deterministic grouping of the map notes, one reduce request per group part
# (topic files), one index request (MEMORY.md), the official checker, and citation statistics.
# Local Ollama only. Submit after all four map shards finish (afterok dependency).
#SBATCH --job-name=fm-corpus-reduce-v5
#SBATCH --partition=vcggpu
#SBATCH --constraint="rtx3090|a5000"
#SBATCH --gres=gpu:2
#SBATCH --cpus-per-task=4
#SBATCH --mem=96G
#SBATCH --time=08:00:00
#SBATCH --output=logs/corpus-memory-v5-reduce-%j.out
#SBATCH --error=logs/corpus-memory-v5-reduce-%j.err

set -euo pipefail
cd /home/csgrad/vbork001/frontiermemory-experiment-20261024
export PATH="${PWD}/bin:${PATH}"
export APPTAINER_CACHEDIR="${PWD}/containers/apptainer-cache"

MODEL="qwen3.8:27b-mtp-q4_K_M"
CONTEXT=65536
MODEL_STORE="/home/csgrad/vbork001/shared-mem-gov-pilot/models"
OLLAMA_SIF="${PWD}/containers/ollama.sif"
RUN_DIR="${PWD}/results/memory-generation-v5"
MANIFEST="${MODEL_STORE}/manifests/registry.ollama.ai/library/${MODEL%%:*}/${MODEL##*:}"

test -s "${OLLAMA_SIF}" && test -s "${MANIFEST}" && test -s "${RUN_DIR}/evidence-index.json"
mkdir -p "${RUN_DIR}/logs"
LOG="${RUN_DIR}/logs/reduce-job-${SLURM_JOB_ID}"
scontrol show job "${SLURM_JOB_ID}" >"${LOG}-slurm-job.txt"
nvidia-smi --query-gpu=name,memory.total,memory.free --format=csv >"${LOG}-gpu.csv"
grep -Eq "RTX 3090|A5000" "${LOG}-gpu.csv"
sha256sum frontiermemory/src/frontier_memory/dream_task/instruction.md \
  frontiermemory/src/frontier_memory/memory.py scripts/generate_corpus_memory_v5.py \
  >"${LOG}-sources.txt"
date --iso-8601=seconds >"${LOG}-started-at.txt"

PORT="$(.venv/bin/python -I -c 'import socket; s=socket.socket(); s.bind(("127.0.0.1", 0)); print(s.getsockname()[1])')"
apptainer exec --fakeroot --nv --bind "${MODEL_STORE}:/models" \
  --env OLLAMA_MODELS=/models --env OLLAMA_HOST="127.0.0.1:${PORT}" \
  --env OLLAMA_CONTEXT_LENGTH="${CONTEXT}" --env OLLAMA_KEEP_ALIVE=30m --env OLLAMA_NUM_PARALLEL=1 \
  "${OLLAMA_SIF}" ollama serve >"${LOG}-ollama-server.log" 2>&1 &
SERVER_PID=$!
cleanup() {
  kill "${SERVER_PID}" 2>/dev/null || true
  wait "${SERVER_PID}" 2>/dev/null || true
  date --iso-8601=seconds >"${LOG}-finished-at.txt"
}
trap cleanup EXIT

READY=0
for attempt in $(seq 1 90); do
  if curl --fail --silent "http://127.0.0.1:${PORT}/api/version" >"${LOG}-api-version.json"; then
    READY=1
    break
  fi
  sleep 2
done
test "${READY}" = 1
curl --fail --silent "http://127.0.0.1:${PORT}/api/tags" >"${LOG}-tags.json"
grep -Fq "${MODEL}" "${LOG}-tags.json"
curl --fail --silent "http://127.0.0.1:${PORT}/api/ps" >"${LOG}-loaded-model.json" || true
.venv/bin/python -I scripts/generate_corpus_memory_v5.py group --run-dir "${RUN_DIR}" >"${LOG}-group.log" 2>&1
.venv/bin/python -I scripts/generate_corpus_memory_v5.py reduce --run-dir "${RUN_DIR}" \
  --api "http://127.0.0.1:${PORT}/api/chat" >"${LOG}-reduce.log" 2>&1
.venv/bin/python -I scripts/generate_corpus_memory_v5.py finalize --run-dir "${RUN_DIR}" \
  --api "http://127.0.0.1:${PORT}/api/chat" >"${LOG}-finalize.log" 2>&1
date --iso-8601=seconds >"${LOG}-reduce-finished-at.txt"
