#!/usr/bin/env bash
# Governor arms G and GR on M3 (preregistration v1, section 2, amendment A1), judge served by local Ollama.
# Environment:
#   VALIDATION_REPORT   path to the passing validation-a1-<model>.json (required)
#   GOV_MODEL           the validated model tag (required)
#   SHARD               i/n: judge only technical units with index % n == i (default 0/1)
#   JUDGE_ONLY          1 to stop after judging the shard (writes judge-cache.jsonl)
#   CACHE_FILES         comma-separated judge caches from earlier shard jobs (merged)
# Outputs (not frozen): results/governor-run-<jobid>/memory-G and memory-GR, plus logs.
#SBATCH --job-name=fm-governor-govern
#SBATCH --partition=vcggpu
#SBATCH --constraint="rtx3090|a5000"
#SBATCH --gres=gpu:2
#SBATCH --cpus-per-task=4
#SBATCH --mem=64G
#SBATCH --time=08:00:00
#SBATCH --output=logs/governor-govern-%j.out
#SBATCH --error=logs/governor-govern-%j.err

set -euo pipefail
cd /home/csgrad/vbork001/frontiermemory-experiment-20261024
export PATH="${PWD}/bin:${PATH}"
export APPTAINER_CACHEDIR="${PWD}/containers/apptainer-cache"

MODEL="${GOV_MODEL:?set GOV_MODEL to the validated model tag}"
CONTEXT=16384
PARALLEL=4
WORKERS=4
MODEL_STORE="/home/csgrad/vbork001/shared-mem-gov-pilot/models"
OLLAMA_SIF="${PWD}/containers/ollama.sif"
RUN_DIR="${PWD}/results/governor-run-${SLURM_JOB_ID}"
VALIDATION="${VALIDATION_REPORT:?set VALIDATION_REPORT}"
MANIFEST="${MODEL_STORE}/manifests/registry.ollama.ai/library/${MODEL%%:*}/${MODEL##*:}"
LOG="${PWD}/logs/governor-govern-${SLURM_JOB_ID}"

test -s "${OLLAMA_SIF}" && test -s "${MANIFEST}" && test -s "${VALIDATION}"
grep -Eq '"gate": "pass"' "${VALIDATION}"
MODEL_TAG="${MODEL}"
mkdir -p "${RUN_DIR}"
scontrol show job "${SLURM_JOB_ID}" >"${LOG}-slurm-job.txt"
nvidia-smi --query-gpu=name,memory.total,memory.free --format=csv >"${LOG}-gpu.csv"
grep -Eq "RTX 3090|A5000" "${LOG}-gpu.csv"
sha256sum scripts/governor/*.py scripts/governor/judge_prompt.md scripts/complete_memory_index.py \
  >"${LOG}-sources.txt"
date --iso-8601=seconds >"${LOG}-started-at.txt"

PORT="$(.venv/bin/python -I -c 'import socket; s=socket.socket(); s.bind(("127.0.0.1", 0)); print(s.getsockname()[1])')"
apptainer exec --fakeroot --nv --bind "${MODEL_STORE}:/models" \
  --env OLLAMA_MODELS=/models --env OLLAMA_HOST="127.0.0.1:${PORT}" \
  --env OLLAMA_CONTEXT_LENGTH="${CONTEXT}" --env OLLAMA_KEEP_ALIVE=30m --env OLLAMA_NUM_PARALLEL="${PARALLEL}" \
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

.venv/bin/python scripts/governor/govern.py --out-dir "${RUN_DIR}" --validation-report "${VALIDATION}" \
  --model "${MODEL}" --model-manifest "${MANIFEST}" --ollama-url "http://127.0.0.1:${PORT}/api/chat" \
  --seed 2027 --workers "${WORKERS}" --shard "${SHARD:-0/1}" ${JUDGE_ONLY:+--judge-only} \
  ${CACHE_FILES:+--cache-files "${CACHE_FILES}"} >"${LOG}-govern.log" 2>&1
