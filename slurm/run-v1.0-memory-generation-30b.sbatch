#!/usr/bin/env bash
#SBATCH --job-name=fm-v1-memory-30b
#SBATCH --partition=vcggpu
#SBATCH --constraint=rtx3090
#SBATCH --gres=gpu:1
#SBATCH --cpus-per-task=4
#SBATCH --mem=32G
#SBATCH --time=01:00:00
#SBATCH --output=logs/v1-memory-30b-%j.out
#SBATCH --error=logs/v1-memory-30b-%j.err

set -euo pipefail
cd /home/csgrad/vbork001/frontiermemory-experiment-20261024

export PATH="${PWD}/bin:${PATH}"
export APPTAINER_CACHEDIR="${PWD}/containers/apptainer-cache"

MODEL=qwen3-coder:30b
OLLAMA_CONTEXT_LENGTH=32768
EXPECTED_GPU_REGEX="${EXPECTED_GPU_REGEX:-GeForce RTX 3090}"
MODEL_STORE=/home/csgrad/vbork001/shared-mem-gov-pilot/models
OLLAMA_SIF="${PWD}/containers/ollama.sif"
RUN_DIR="${PWD}/results/memory-generation-v1.0-opencode-20261026"
EVIDENCE="${RUN_DIR}/evidence-input.md"

mkdir -p "${RUN_DIR}/run"
test -s "${EVIDENCE}"
test -s "${OLLAMA_SIF}"
test -d "${MODEL_STORE}"
printf '%s\n' "${EXPECTED_GPU_REGEX}" >"${RUN_DIR}/run/expected-gpu-regex.txt"
printf '%s\n' "${MODEL}" >"${RUN_DIR}/run/model.txt"
printf '%s\n' "${OLLAMA_CONTEXT_LENGTH}" >"${RUN_DIR}/run/requested-context.txt"
date --iso-8601=seconds >"${RUN_DIR}/run/started-at.txt"
scontrol show job "${SLURM_JOB_ID}" >"${RUN_DIR}/run/slurm-job.txt"
nvidia-smi -q >"${RUN_DIR}/run/nvidia-smi.txt"
nvidia-smi --query-gpu=name,memory.total,memory.free --format=csv >"${RUN_DIR}/run/gpu.csv"
grep -Eq "${EXPECTED_GPU_REGEX}" "${RUN_DIR}/run/gpu.csv"
apptainer exec --fakeroot "${OLLAMA_SIF}" ollama --version >"${RUN_DIR}/run/ollama-version.txt" 2>&1

apptainer exec --fakeroot --nv \
  --bind "${MODEL_STORE}:/models" \
  --env OLLAMA_MODELS=/models \
  --env OLLAMA_HOST=127.0.0.1:11434 \
  --env OLLAMA_CONTEXT_LENGTH="${OLLAMA_CONTEXT_LENGTH}" \
  --env OLLAMA_KEEP_ALIVE=20m \
  "${OLLAMA_SIF}" ollama serve >"${RUN_DIR}/run/ollama-server.log" 2>&1 &
SERVER_PID=$!
cleanup() {
  kill "${SERVER_PID}" 2>/dev/null || true
  wait "${SERVER_PID}" 2>/dev/null || true
  date --iso-8601=seconds >"${RUN_DIR}/run/finished-at.txt"
}
trap cleanup EXIT

READY=0
for attempt in $(seq 1 60); do
  if curl --fail --silent http://127.0.0.1:11434/api/version >"${RUN_DIR}/run/api-version.json"; then
    READY=1
    break
  fi
  sleep 2
done
test "${READY}" = 1
curl --fail --silent http://127.0.0.1:11434/api/tags >"${RUN_DIR}/run/tags.json"
grep -q "${MODEL}" "${RUN_DIR}/run/tags.json"

.venv/bin/python scripts/synthesize_historical_memory.py \
  --evidence "${EVIDENCE}" \
  --output "${RUN_DIR}/MEMORY-candidate.md" \
  --metrics "${RUN_DIR}/run/metrics.json" \
  --request-record "${RUN_DIR}/run/request.json" \
  --model "${MODEL}" \
  --context "${OLLAMA_CONTEXT_LENGTH}" \
  >"${RUN_DIR}/run/generation.log" 2>&1

test -s "${RUN_DIR}/MEMORY-candidate.md"
curl --fail --silent http://127.0.0.1:11434/api/ps >"${RUN_DIR}/run/loaded-model.json"
python3 - "${RUN_DIR}/run/loaded-model.json" "${MODEL}" "${OLLAMA_CONTEXT_LENGTH}" <<'PY'
import json
import sys
from pathlib import Path

payload = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
model_name = sys.argv[2]
expected_context = int(sys.argv[3])
loaded = [item for item in payload.get("models", []) if item.get("name") == model_name]
if not loaded:
    raise SystemExit(f"Model not present in Ollama /api/ps: {model_name}")
actual_context = int(loaded[0].get("context_length") or 0)
if actual_context != expected_context:
    raise SystemExit(f"Loaded context {actual_context} != requested {expected_context}")
print(json.dumps({"model": model_name, "context_length": actual_context, "size_vram": loaded[0].get("size_vram")}))
PY

.venv/bin/python scripts/verify_memory_citations.py \
  --corpus data/corpus/joint-674-v1.0 \
  --evidence "${EVIDENCE}" \
  --memory "${RUN_DIR}/MEMORY-candidate.md" \
  --report "${RUN_DIR}/run/citation-check.json" \
  >"${RUN_DIR}/run/citation-check.log" 2>&1
date --iso-8601=seconds >"${RUN_DIR}/run/generation-finished-at.txt"
