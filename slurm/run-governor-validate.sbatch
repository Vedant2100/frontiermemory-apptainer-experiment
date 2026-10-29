#!/usr/bin/env bash
# Governor judge validation (preregistration v1, section 2.6, amendment A1): 100 sampled M3 units, perturbed and
# judged against their cited evidence with a local Ollama model. Exits 3 when the gate fails
# (sensitivity >= 0.6 and specificity >= 0.8), which blocks the dependent govern job (afterok).
# Model: GOV_MODEL (default gemma3:27b). Outputs: results/governor-run-<jobid>/validation/validation-a1-<model>.json.
# Submit: sbatch --export=ALL,GOV_MODEL='qwen3.8:27b-mtp-q4_K_M' slurm/run-governor-validate.sbatch
#SBATCH --job-name=fm-governor-validate
#SBATCH --partition=vcggpu
#SBATCH --constraint="rtx3090|a5000"
#SBATCH --gres=gpu:2
#SBATCH --cpus-per-task=4
#SBATCH --mem=64G
#SBATCH --time=02:00:00
#SBATCH --output=logs/governor-validate-%j.out
#SBATCH --error=logs/governor-validate-%j.err

set -euo pipefail
cd /home/csgrad/vbork001/frontiermemory-experiment-20261024
export PATH="${PWD}/bin:${PATH}"
export APPTAINER_CACHEDIR="${PWD}/containers/apptainer-cache"

MODEL="${GOV_MODEL:-gemma3:27b}"
CONTEXT=16384
PARALLEL=4
MODEL_STORE="/home/csgrad/vbork001/shared-mem-gov-pilot/models"
OLLAMA_SIF="${PWD}/containers/ollama.sif"
RUN_DIR="${PWD}/results/governor-run-${SLURM_JOB_ID}"
OUT_DIR="${RUN_DIR}/validation"
MANIFEST="${MODEL_STORE}/manifests/registry.ollama.ai/library/${MODEL%%:*}/${MODEL##*:}"
LOG="${PWD}/logs/governor-validate-${SLURM_JOB_ID}"

test -s "${OLLAMA_SIF}" && test -s "${MANIFEST}" && test -s "${PWD}/results/memory-generation-v5/evidence-index.json"
mkdir -p "${OUT_DIR}"
scontrol show job "${SLURM_JOB_ID}" >"${LOG}-slurm-job.txt"
nvidia-smi --query-gpu=name,memory.total,memory.free --format=csv >"${LOG}-gpu.csv"
grep -Eq "RTX 3090|A5000" "${LOG}-gpu.csv"
sha256sum scripts/governor/*.py scripts/governor/judge_prompt.md >"${LOG}-sources.txt"
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

rc=0
.venv/bin/python scripts/governor/validate.py --out-dir "${OUT_DIR}" --model "${MODEL}" \
  --model-manifest "${MANIFEST}" --ollama-url "http://127.0.0.1:${PORT}/api/chat" --seed 2027 --workers "${PARALLEL}" \
  >"${LOG}-validate.log" 2>&1 || rc=$?
echo "validate exit ${rc}" >>"${LOG}-validate.log"
date --iso-8601=seconds >"${LOG}-validate-finished-at.txt"
exit "${rc}"
