#!/usr/bin/env bash
# Memory v5 map shard: one request per pinned-corpus trajectory (whole corpus, 674 files),
# using the verbatim official instruction plus a minimal framing sentence. Local Ollama only.
# Submit once per shard: sbatch --export=ALL,SHARD=<i>,SHARDS=4 slurm/run-corpus-memory-v5-map.sbatch
#SBATCH --job-name=fm-corpus-map-v5
#SBATCH --partition=vcggpu
#SBATCH --constraint="rtx3090|a5000"
#SBATCH --gres=gpu:2
#SBATCH --cpus-per-task=4
#SBATCH --mem=96G
#SBATCH --time=10:00:00
#SBATCH --output=logs/corpus-memory-v5-map-%j.out
#SBATCH --error=logs/corpus-memory-v5-map-%j.err

set -euo pipefail
cd /home/csgrad/vbork001/frontiermemory-experiment-20261024
export PATH="${PWD}/bin:${PATH}"
export APPTAINER_CACHEDIR="${PWD}/containers/apptainer-cache"

SHARD="${SHARD:?set SHARD}"
SHARDS="${SHARDS:?set SHARDS}"
MODEL="qwen3.8:27b-mtp-q4_K_M"
CONTEXT=65536
MODEL_STORE="/home/csgrad/vbork001/shared-mem-gov-pilot/models"
OLLAMA_SIF="${PWD}/containers/ollama.sif"
RUN_DIR="${PWD}/results/memory-generation-v5"
MANIFEST="${MODEL_STORE}/manifests/registry.ollama.ai/library/${MODEL%%:*}/${MODEL##*:}"

test -s "${OLLAMA_SIF}" && test -s "${MANIFEST}" && test -s "${RUN_DIR}/evidence-index.json"
mkdir -p "${RUN_DIR}/logs"
LOG="${RUN_DIR}/logs/map-job-${SLURM_JOB_ID}-shard-${SHARD}"
scontrol show job "${SLURM_JOB_ID}" >"${LOG}-slurm-job.txt"
nvidia-smi --query-gpu=name,memory.total,memory.free --format=csv >"${LOG}-gpu.csv"
grep -Eq "RTX 3090|A5000" "${LOG}-gpu.csv"
sha256sum frontiermemory/src/frontier_memory/dream_task/instruction.md \
  frontiermemory/src/frontier_memory/memory.py "${RUN_DIR}/evidence-index.json" \
  scripts/build_corpus_evidence_v5.py scripts/generate_corpus_memory_v5.py >"${LOG}-sources.txt"
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
curl --fail --silent --show-error "http://127.0.0.1:${PORT}/api/chat" \
  -H 'Content-Type: application/json' \
  -d "{\"model\":\"${MODEL}\",\"stream\":false,\"think\":false,\"messages\":[{\"role\":\"user\",\"content\":\"Reply READY.\"}],\"options\":{\"num_ctx\":${CONTEXT},\"num_predict\":16,\"temperature\":0}}" \
  >"${LOG}-smoke-response.json"
curl --fail --silent "http://127.0.0.1:${PORT}/api/ps" >"${LOG}-loaded-model.json"
.venv/bin/python -I - "${LOG}-loaded-model.json" "${MODEL}" "${CONTEXT}" <<'PY'
import json, pathlib, sys
payload = json.loads(pathlib.Path(sys.argv[1]).read_text(encoding="utf-8"))
model = next((m for m in payload.get("models", []) if m.get("name") == sys.argv[2]), None)
if model is None or int(model.get("context_length") or 0) != int(sys.argv[3]):
    raise SystemExit("Ollama model/context preflight failed")
print("preflight ok:", model["name"], model["context_length"], model.get("size_vram"))
PY

.venv/bin/python -I scripts/generate_corpus_memory_v5.py map --run-dir "${RUN_DIR}" \
  --api "http://127.0.0.1:${PORT}/api/chat" --shard "${SHARD}" --shards "${SHARDS}" \
  >"${LOG}-map.log" 2>&1
date --iso-8601=seconds >"${LOG}-map-finished-at.txt"
