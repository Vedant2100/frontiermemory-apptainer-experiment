#!/usr/bin/env bash
# Synthesize memory only from the previously audited, corpus-derived evidence
# pack. The target task, verifier, and run artifacts are not model inputs.
#SBATCH --job-name=fm-word2vec-memory
#SBATCH --partition=vcggpu
#SBATCH --constraint=rtx3090
#SBATCH --gres=gpu:2
#SBATCH --cpus-per-task=4
#SBATCH --mem=96G
#SBATCH --time=00:20:00
#SBATCH --output=logs/word2vec-memory-%j.out
#SBATCH --error=logs/word2vec-memory-%j.err

set -euo pipefail
cd /home/csgrad/vbork001/frontiermemory-experiment-20261024
export PATH="${PWD}/bin:${PATH}"
export APPTAINER_CACHEDIR="${PWD}/containers/apptainer-cache"

MODEL="qwen3.8:27b-mtp-q4_K_M"
CONTEXT=65536
EXPECTED_GPU="${EXPECTED_GPU:-NVIDIA GeForce RTX 3090}"
MODEL_STORE="/home/csgrad/vbork001/shared-mem-gov-pilot/models"
OLLAMA_SIF="${PWD}/containers/ollama.sif"
CORPUS="${PWD}/data/corpus/joint-674-v1.0-pinned"
EVIDENCE="${PWD}/results/memory-generation-v1.0-opencode-20261026/evidence-input.md"
EVIDENCE_AUDIT="${PWD}/results/memory-generation-v1.0-opencode-20261026/evidence-audit.json"
RUN_DIR="${PWD}/results/word2vec-openhands/memory-generation/job-${SLURM_JOB_ID}"

MANIFEST="${MODEL_STORE}/manifests/registry.ollama.ai/library/${MODEL%%:*}/${MODEL##*:}"
test -s "${OLLAMA_SIF}" && test -s "${MANIFEST}" && test -s "${EVIDENCE}" && test -s "${EVIDENCE_AUDIT}"
mkdir -p "${RUN_DIR}" logs
date --iso-8601=seconds >"${RUN_DIR}/started-at.txt"
scontrol show job "${SLURM_JOB_ID}" >"${RUN_DIR}/slurm-job.txt"
nvidia-smi --query-gpu=name,memory.total,memory.free --format=csv >"${RUN_DIR}/gpu.csv"
grep -Fq "${EXPECTED_GPU}" "${RUN_DIR}/gpu.csv"
sha256sum "${CORPUS}/SHA256SUMS" "${EVIDENCE}" >"${RUN_DIR}/source-sha256.txt"
.venv/bin/python - "${EVIDENCE}" "${EVIDENCE_AUDIT}" "${CONTEXT}" <<'PY'
import hashlib, json, pathlib, sys
evidence, audit = map(pathlib.Path, sys.argv[1:3])
record = json.loads(audit.read_text(encoding="utf-8"))
digest = hashlib.sha256(evidence.read_bytes()).hexdigest()
if record.get("manifest_sha256") != "c7d31214ed20af4f14f46c4b9a838ebc9aa35a9491dfbce0fa50f7aa456eedd1":
    raise SystemExit("Evidence audit does not reference the pinned v1.0 corpus")
if record.get("evidence_input_sha256") != digest:
    raise SystemExit("Evidence input differs from its audited checksum")
if record.get("generation_input_contains_current_task") is not False:
    raise SystemExit("Evidence audit does not establish target-task exclusion")
text = evidence.read_text(encoding="utf-8").lower()
if any(marker in text for marker in ("build-word2vec-pipeline", "word2vec", "gensim", "nltk")):
    raise SystemExit("Target-specific text is present in the memory-generation input")
print(json.dumps({"corpus_manifest_sha256": record["manifest_sha256"], "evidence_sha256": digest, "evidence_bytes": evidence.stat().st_size, "target_task_present": False, "requested_context": int(sys.argv[3])}, indent=2))
PY

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
  -d "{\"model\":\"${MODEL}\",\"stream\":false,\"messages\":[{\"role\":\"user\",\"content\":\"Reply READY.\"}],\"options\":{\"num_ctx\":${CONTEXT},\"num_predict\":16,\"temperature\":0}}" \
  >"${RUN_DIR}/smoke-response.json"
curl --fail --silent http://127.0.0.1:11434/api/ps >"${RUN_DIR}/loaded-model-before.json"
nvidia-smi --query-gpu=name,memory.used,memory.total --format=csv >"${RUN_DIR}/gpu-after-model-load.csv"
.venv/bin/python - "${RUN_DIR}/loaded-model-before.json" "${MODEL}" "${CONTEXT}" >"${RUN_DIR}/loaded-model-summary.json" <<'PY'
import json, pathlib, sys
payload = json.loads(pathlib.Path(sys.argv[1]).read_text(encoding="utf-8"))
model = next((m for m in payload.get("models", []) if m.get("name") == sys.argv[2]), None)
if model is None or int(model.get("context_length") or 0) != int(sys.argv[3]):
    raise SystemExit("Ollama model/context preflight failed")
print(json.dumps({"model": model["name"], "context_length": model["context_length"], "size_vram": model.get("size_vram")}, indent=2))
PY

.venv/bin/python scripts/synthesize_historical_memory.py \
  --evidence "${EVIDENCE}" \
  --output "${RUN_DIR}/MEMORY-candidate.md" \
  --metrics "${RUN_DIR}/metrics.json" \
  --request-record "${RUN_DIR}/request.json" \
  --model "${MODEL}" \
  --context "${CONTEXT}" >"${RUN_DIR}/generation.log" 2>&1

.venv/bin/python scripts/verify_memory_citations.py \
  --corpus "${CORPUS}" --evidence "${EVIDENCE}" \
  --memory "${RUN_DIR}/MEMORY-candidate.md" \
  --report "${RUN_DIR}/citation-check.json" >"${RUN_DIR}/citation-check.log" 2>&1
sha256sum "${RUN_DIR}/MEMORY-candidate.md" >"${RUN_DIR}/memory-sha256.txt"
date --iso-8601=seconds >"${RUN_DIR}/generation-finished-at.txt"
