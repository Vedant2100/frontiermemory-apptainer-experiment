#!/usr/bin/env bash
# Memory v3 generation: family-selected evidence (same 14 trajectories as v2, with
# no per-step truncation except observation and whole-trajectory caps) -> per-trajectory
# map requests (up to 10 lessons) -> one reduce request (<= 8192 bytes, with a cited
# reference recipe) -> MEMORY.md, then the v3 citation check. The target task, its
# verifier, and the repo are not inputs. Same local Ollama model and GPU setup as v2.
#SBATCH --job-name=fm-w2v-memory-v3
#SBATCH --partition=vcggpu
#SBATCH --constraint=rtx3090
#SBATCH --gres=gpu:2
#SBATCH --cpus-per-task=4
#SBATCH --mem=96G
#SBATCH --time=01:30:00
#SBATCH --output=logs/word2vec-memory-v3-%j.out
#SBATCH --error=logs/word2vec-memory-v3-%j.err

set -euo pipefail
cd /home/csgrad/vbork001/frontiermemory-experiment-20261024
export PATH="${PWD}/bin:${PATH}"
export APPTAINER_CACHEDIR="${PWD}/containers/apptainer-cache"

MODEL="qwen3.8:27b-mtp-q4_K_M"
CONTEXT=65536
TEMPERATURE=0.1
EXPECTED_GPU="${EXPECTED_GPU:-NVIDIA GeForce RTX 3090}"
MODEL_STORE="/home/csgrad/vbork001/shared-mem-gov-pilot/models"
OLLAMA_SIF="${PWD}/containers/ollama.sif"
CORPUS="${PWD}/data/corpus/joint-674-v1.0-pinned"
RUN_DIR="${PWD}/results/word2vec-openhands/memory-v3/job-${SLURM_JOB_ID}"

MANIFEST="${MODEL_STORE}/manifests/registry.ollama.ai/library/${MODEL%%:*}/${MODEL##*:}"
test -s "${OLLAMA_SIF}" && test -s "${MANIFEST}" && test -d "${CORPUS}/inputs"
mkdir -p "${RUN_DIR}" logs
date --iso-8601=seconds >"${RUN_DIR}/started-at.txt"
scontrol show job "${SLURM_JOB_ID}" >"${RUN_DIR}/slurm-job.txt"
nvidia-smi --query-gpu=name,memory.total,memory.free --format=csv >"${RUN_DIR}/gpu.csv"
grep -Fq "${EXPECTED_GPU}" "${RUN_DIR}/gpu.csv"
sha256sum "${CORPUS}/SHA256SUMS" "${PWD}/scripts/build_family_evidence_v3.py" \
  "${PWD}/scripts/generate_family_memory_v3.py" "${PWD}/scripts/verify_memory_v3_citations.py" \
  >"${RUN_DIR}/source-sha256.txt"

# CPU step: condensed evidence for the fixed 14-file family set (no target inputs).
.venv/bin/python -I scripts/build_family_evidence_v3.py \
  --corpus "${CORPUS}" --out-dir "${RUN_DIR}" >"${RUN_DIR}/evidence-build.log" 2>&1

apptainer exec --fakeroot --nv --bind "${MODEL_STORE}:/models" \
  --env OLLAMA_MODELS=/models --env OLLAMA_HOST=127.0.0.1:11434 \
  --env OLLAMA_CONTEXT_LENGTH="${CONTEXT}" --env OLLAMA_KEEP_ALIVE=20m \
  "${OLLAMA_SIF}" ollama serve >"${RUN_DIR}/ollama-server.log" 2>&1 &
SERVER_PID=$!
cleanup() {
  kill "${SERVER_PID}" 2>/dev/null || true
  wait "${SERVER_PID}" 2>/dev/null || true
  date --iso-8601=seconds >"${RUN_DIR}/finished-at.txt"
}
trap cleanup EXIT

READY=0
for attempt in $(seq 1 60); do
  if curl --fail --silent http://127.0.0.1:11434/api/version >"${RUN_DIR}/api-version.json"; then
    READY=1
    break
  fi
  sleep 2
done
test "${READY}" = 1
curl --fail --silent http://127.0.0.1:11434/api/tags >"${RUN_DIR}/tags.json"
grep -Fq "${MODEL}" "${RUN_DIR}/tags.json"
curl --fail --silent --show-error http://127.0.0.1:11434/api/chat \
  -H 'Content-Type: application/json' \
  -d "{\"model\":\"${MODEL}\",\"stream\":false,\"think\":false,\"messages\":[{\"role\":\"user\",\"content\":\"Reply READY.\"}],\"options\":{\"num_ctx\":${CONTEXT},\"num_predict\":16,\"temperature\":0}}" \
  >"${RUN_DIR}/smoke-response.json"
curl --fail --silent http://127.0.0.1:11434/api/ps >"${RUN_DIR}/loaded-model-before.json"
nvidia-smi --query-gpu=name,memory.used,memory.total --format=csv >"${RUN_DIR}/gpu-after-model-load.csv"
.venv/bin/python -I - "${RUN_DIR}/loaded-model-before.json" "${MODEL}" "${CONTEXT}" >"${RUN_DIR}/loaded-model-summary.json" <<'PY'
import json, pathlib, sys
payload = json.loads(pathlib.Path(sys.argv[1]).read_text(encoding="utf-8"))
model = next((m for m in payload.get("models", []) if m.get("name") == sys.argv[2]), None)
if model is None or int(model.get("context_length") or 0) != int(sys.argv[3]):
    raise SystemExit("Ollama model/context preflight failed")
print(json.dumps({"model": model["name"], "context_length": model["context_length"], "size_vram": model.get("size_vram")}, indent=2))
PY

# Map (one request per trajectory) and reduce (one or two requests), thinking disabled.
.venv/bin/python -I scripts/generate_family_memory_v3.py \
  --job-dir "${RUN_DIR}" --model "${MODEL}" --context "${CONTEXT}" \
  --temperature "${TEMPERATURE}" >"${RUN_DIR}/generation.log" 2>&1

.venv/bin/python -I scripts/verify_memory_v3_citations.py \
  --corpus "${CORPUS}" --memory "${RUN_DIR}/MEMORY.md" \
  --report "${RUN_DIR}/citation-check.json" >"${RUN_DIR}/citation-check.log" 2>&1
sha256sum "${RUN_DIR}/MEMORY.md" >"${RUN_DIR}/memory-sha256.txt"
date --iso-8601=seconds >"${RUN_DIR}/generation-finished-at.txt"
