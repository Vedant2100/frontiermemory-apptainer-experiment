#!/usr/bin/env bash
#SBATCH --job-name=fm-awilix-opencode-A
#SBATCH --partition=gpu
#SBATCH --constraint=a6000ada
#SBATCH --gres=gpu:1
#SBATCH --cpus-per-task=8
#SBATCH --mem=48G
#SBATCH --time=03:00:00
#SBATCH --output=logs/awilix-opencode-A-%j.out
#SBATCH --error=logs/awilix-opencode-A-%j.err

set -euo pipefail
cd /home/csgrad/vbork001/frontiermemory-experiment-20261024

export PATH="${PWD}/bin:${PATH}"
export APPTAINER_CACHEDIR="${PWD}/containers/apptainer-cache"
export OLLAMA_CONTEXT_LENGTH=65536
export OLLAMA_KEEP_ALIVE=20m
export OLLAMA_HOST=127.0.0.1:11434
export OLLAMA_MODELS=/models
export TERM=xterm-256color

MODEL=qwen3-coder:30b
MODEL_STORE=/home/csgrad/vbork001/shared-mem-gov-pilot/models
OLLAMA_SIF="${PWD}/containers/ollama.sif"
TASK_PATH="${PWD}/build/awilix-release-tier-implicit-apptainer"
JOB_NAME="frontiermemory-awilix-implicit-v1.0-opencode-qwen3-coder-30b-A-no-memory-${SLURM_JOB_ID}"
RUN_DIR="${PWD}/results/opencode-awilix-A/job-${SLURM_JOB_ID}"
mkdir -p "${RUN_DIR}/ollama"

date --iso-8601=seconds >"${RUN_DIR}/started-at.txt"
scontrol show job "${SLURM_JOB_ID}" >"${RUN_DIR}/slurm-job.txt"
nvidia-smi -q >"${RUN_DIR}/nvidia-smi.txt"
nvidia-smi --query-gpu=name,memory.total,memory.free --format=csv >"${RUN_DIR}/gpu.csv"
grep -q 'RTX 6000 Ada' "${RUN_DIR}/gpu.csv"
.venv/bin/harbor --version >"${RUN_DIR}/harbor-version.txt"
apptainer version >"${RUN_DIR}/apptainer-version.txt"
apptainer exec --fakeroot "${OLLAMA_SIF}" ollama --version >"${RUN_DIR}/ollama-version.txt" 2>&1

test -f "${OLLAMA_SIF}"
test -d "${MODEL_STORE}"
test -f "${TASK_PATH}/task.toml"

apptainer exec --fakeroot --nv \
  --bind "${MODEL_STORE}:/models" \
  --env OLLAMA_MODELS=/models \
  --env OLLAMA_HOST=127.0.0.1:11434 \
  --env OLLAMA_CONTEXT_LENGTH="${OLLAMA_CONTEXT_LENGTH}" \
  --env OLLAMA_KEEP_ALIVE="${OLLAMA_KEEP_ALIVE}" \
  "${OLLAMA_SIF}" ollama serve >"${RUN_DIR}/ollama/server.log" 2>&1 &
SERVER_PID=$!
CONTEXT_PID=""
HARBOR_PID=""
cleanup() {
  if [[ -n "${CONTEXT_PID}" ]]; then
    kill "${CONTEXT_PID}" 2>/dev/null || true
    wait "${CONTEXT_PID}" 2>/dev/null || true
  fi
  if [[ -n "${SERVER_PID}" ]]; then
    kill "${SERVER_PID}" 2>/dev/null || true
    wait "${SERVER_PID}" 2>/dev/null || true
  fi
  date --iso-8601=seconds >"${RUN_DIR}/finished-at.txt"
}
trap cleanup EXIT

READY=0
for attempt in $(seq 1 60); do
  if curl --fail --silent http://127.0.0.1:11434/api/version >"${RUN_DIR}/ollama/api-version.json"; then
    READY=1
    break
  fi
  sleep 2
done
test "${READY}" = 1

curl --fail --silent http://127.0.0.1:11434/api/tags >"${RUN_DIR}/ollama/tags-before.json"
if ! grep -q 'qwen3-coder:30b' "${RUN_DIR}/ollama/tags-before.json"; then
  apptainer exec --fakeroot --nv \
    --bind "${MODEL_STORE}:/models" \
    --env OLLAMA_MODELS=/models \
    --env OLLAMA_HOST=127.0.0.1:11434 \
    "${OLLAMA_SIF}" ollama pull "${MODEL}" >"${RUN_DIR}/ollama/pull.log" 2>&1
fi
curl --fail --silent http://127.0.0.1:11434/api/tags >"${RUN_DIR}/ollama/tags.json"
grep -q 'qwen3-coder:30b' "${RUN_DIR}/ollama/tags.json"

python3 - "${RUN_DIR}/ollama" >"${RUN_DIR}/ollama/context-poller.log" 2>&1 <<'PY' &
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.request import urlopen

out = Path(sys.argv[1]) / "loaded-context.jsonl"
while True:
    try:
        with urlopen("http://127.0.0.1:11434/api/ps", timeout=3) as response:
            payload = json.load(response)
        models = payload.get("models", [])
        record = {
            "observed_at": datetime.now(timezone.utc).isoformat(),
            "models": [
                {
                    "name": model.get("name"),
                    "context_length": model.get("context_length"),
                    "size_vram": model.get("size_vram"),
                }
                for model in models
            ],
        }
        with out.open("a", encoding="utf-8") as stream:
            stream.write(json.dumps(record) + "\n")
            stream.flush()
    except Exception as error:
        with (Path(sys.argv[1]) / "context-poll-errors.log").open("a", encoding="utf-8") as stream:
            stream.write(f"{datetime.now(timezone.utc).isoformat()} {error}\n")
    time.sleep(5)
PY
CONTEXT_PID=$!

set +e
.venv/bin/harbor run \
  --config configs/opencode-qwen3-coder-30b-A.yaml \
  --path "${TASK_PATH}" \
  --env singularity \
  --jobs-dir jobs \
  --job-name "${JOB_NAME}" \
  --n-attempts 1 \
  --n-concurrent 1 \
  --yes >"${RUN_DIR}/harbor.log" 2>&1 &
HARBOR_PID=$!
python3 scripts/watch_harbor_opencode.py \
  --jobs-dir jobs \
  --job-name "${JOB_NAME}" \
  --harbor-pid "${HARBOR_PID}" \
  --marker "${RUN_DIR}/repetition-stop.json" \
  >"${RUN_DIR}/watch.log" 2>&1 &
WATCH_PID=$!
wait "${HARBOR_PID}"
HARBOR_EXIT=$?
wait "${WATCH_PID}" 2>/dev/null
set -e
printf '%s\n' "${HARBOR_EXIT}" >"${RUN_DIR}/harbor-exit-code.txt"

curl --fail --silent http://127.0.0.1:11434/api/ps >"${RUN_DIR}/ollama/loaded-model-at-end.json" || true
curl --fail --silent http://127.0.0.1:11434/api/tags >"${RUN_DIR}/ollama/tags-after.json" || true
find "jobs/${JOB_NAME}" -maxdepth 8 -type f -print >"${RUN_DIR}/harbor-files.txt" 2>/dev/null || true

exit "${HARBOR_EXIT}"
