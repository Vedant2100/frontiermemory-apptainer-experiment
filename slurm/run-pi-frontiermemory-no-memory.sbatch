#!/usr/bin/env bash
#SBATCH --job-name=fm-pi-frontiermemory
#SBATCH --partition=vcggpu
#SBATCH --constraint=rtx3090
#SBATCH --gres=gpu:1
#SBATCH --cpus-per-task=8
#SBATCH --mem=48G
#SBATCH --time=00:35:00
#SBATCH --output=logs/pi-frontiermemory-%j.out
#SBATCH --error=logs/pi-frontiermemory-%j.err

set -euo pipefail
cd /home/csgrad/vbork001/frontiermemory-experiment-20261024

export PATH="${PWD}/bin:${PATH}"
export APPTAINER_CACHEDIR="${PWD}/containers/apptainer-cache"
export OLLAMA_CONTEXT_LENGTH=32768
export OLLAMA_KEEP_ALIVE=20m
export OLLAMA_HOST=127.0.0.1:11434
export OLLAMA_MODELS=/models
export TERM=xterm-256color

TASK_ID="${TASK_ID:?Set TASK_ID to opencode-reliability-canary or cattrs-compositional-changelog}"
case "${TASK_ID}" in
  opencode-reliability-canary|cattrs-compositional-changelog) ;;
  *) echo "Unsupported TASK_ID: ${TASK_ID}" >&2; exit 2 ;;
esac

MODEL="${MODEL:-qwen3.8:27b-mtp-q4_K_M}"
MODEL_SLUG="${MODEL//:/-}"
MODEL_STORE="/home/csgrad/vbork001/shared-mem-gov-pilot/models"
OLLAMA_SIF="${PWD}/containers/ollama.sif"
TASK_PATH="${PWD}/build/opencode-frontiermemory-tasks/${TASK_ID}"
RUN_DIR="${PWD}/results/pi-frontiermemory-no-memory/job-${SLURM_JOB_ID}"
HARBOR_JOB_NAME="frontiermemory-v1.0-${TASK_ID}-pi-${MODEL_SLUG}-no-memory-${SLURM_JOB_ID}"

test -f "${OLLAMA_SIF}"
test -d "${MODEL_STORE}"
test -f "${TASK_PATH}/task.toml"
test -f "${TASK_PATH}/apptainer-adaptation.json"
mkdir -p "${RUN_DIR}/ollama"
date --iso-8601=seconds >"${RUN_DIR}/started-at.txt"
scontrol show job "${SLURM_JOB_ID}" >"${RUN_DIR}/slurm-job.txt"
nvidia-smi -q >"${RUN_DIR}/nvidia-smi.txt"
nvidia-smi --query-gpu=name,memory.total,memory.free --format=csv >"${RUN_DIR}/gpu.csv"
grep -Eq 'GeForce RTX 3090' "${RUN_DIR}/gpu.csv"
.venv/bin/harbor --version >"${RUN_DIR}/harbor-version.txt"
apptainer version >"${RUN_DIR}/apptainer-version.txt"
rg --version >"${RUN_DIR}/host-ripgrep-version.txt"
apptainer exec --fakeroot "${OLLAMA_SIF}" ollama --version >"${RUN_DIR}/ollama-version.txt" 2>&1
printf '%s\n' "${MODEL}" >"${RUN_DIR}/model.txt"
printf '%s\n' "${OLLAMA_CONTEXT_LENGTH}" >"${RUN_DIR}/requested-context.txt"
sha256sum "${TASK_PATH}/task.toml" >"${RUN_DIR}/task-toml.sha256"

apptainer exec --fakeroot --nv \
  --bind "${MODEL_STORE}:/models" \
  --env OLLAMA_MODELS=/models \
  --env OLLAMA_HOST=127.0.0.1:11434 \
  --env OLLAMA_CONTEXT_LENGTH="${OLLAMA_CONTEXT_LENGTH}" \
  --env OLLAMA_KEEP_ALIVE="${OLLAMA_KEEP_ALIVE}" \
  "${OLLAMA_SIF}" ollama serve >"${RUN_DIR}/ollama/server.log" 2>&1 &
SERVER_PID=$!
CONTEXT_PID=""
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
curl --fail --silent http://127.0.0.1:11434/api/tags >"${RUN_DIR}/ollama/tags.json"
if ! grep -q "${MODEL}" "${RUN_DIR}/ollama/tags.json"; then
  echo "Required model is absent; refusing to download a model: ${MODEL}" >&2
  exit 3
fi
.venv/bin/python scripts/probe_ollama_thinking.py \
  --model "${MODEL}" \
  --output-dir "${RUN_DIR}/ollama/thinking-probe"

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
        record = {
            "observed_at": datetime.now(timezone.utc).isoformat(),
            "models": [
                {
                    "name": model.get("name"),
                    "context_length": model.get("context_length"),
                    "size_vram": model.get("size_vram"),
                }
                for model in payload.get("models", [])
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

PROMPT_TEMPLATE="${RUN_DIR}/prompt-template.md"
cat >"${PROMPT_TEMPLATE}" <<'PROMPT'
Work in the task repository at /app (the current working directory). Use repository-relative paths for reads and edits.

The historical-memory section is intentionally empty for this no-memory run:

<historical_memory>
</historical_memory>

Execution requirements:
- Use the harness's native tools. Text such as <tool_call> or <function=...> is ordinary text, not an executed tool call.
- Do not stop after inspection. Make the requested code changes, run a focused test, and inspect the resulting diff before finishing.
- Base exact-match edits on the current file contents. If an edit says the old text does not match, re-read the file and do not retry with guessed text. Use a direct write or Bash with a small Python script/heredoc based on the inspected file instead.
- If blocked, report the concrete blocker and do not imply the task is complete.

Current task instruction:
{{ instruction }}
PROMPT
sha256sum "${PROMPT_TEMPLATE}" >"${RUN_DIR}/prompt-template.sha256"

set +e
timeout --signal=INT --kill-after=15s 900s .venv/bin/harbor run \
  --path "${TASK_PATH}" \
  --env singularity \
  --jobs-dir jobs \
  --job-name "${HARBOR_JOB_NAME}" \
  --agent pi \
  --model "ollama/${MODEL}" \
  --agent-kwarg version=0.85.1 \
  --agent-kwarg model_api=openai-completions \
  --agent-kwarg thinking=off \
  --agent-kwarg max_turns=8 \
  --agent-kwarg "prompt_template_path=${PROMPT_TEMPLATE}" \
  --agent-env "PATH=/staging/env_files/shims:/staging/env_files/pi-runtime/bin:/staging/env_files/opencode-runtime/node/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin" \
  --agent-env NPM_CONFIG_PREFIX=/staging/env_files/pi-runtime \
  --agent-env OLLAMA_API_KEY=local-ollama-no-auth \
  --agent-env OLLAMA_BASE_URL=http://127.0.0.1:11434/v1 \
  --n-attempts 1 \
  --n-concurrent 1 \
  --agent-timeout-multiplier 0.5 \
  --agent-setup-timeout-multiplier 0.25 \
  --yes >"${RUN_DIR}/harbor.log" 2>&1
HARBOR_EXIT=$?
set -e
printf '%s\n' "${HARBOR_EXIT}" >"${RUN_DIR}/harbor-exit-code.txt"
curl --fail --silent http://127.0.0.1:11434/api/ps >"${RUN_DIR}/ollama/loaded-model-after-agent.json" || true

RESULT_FILE="$(find "jobs/${HARBOR_JOB_NAME}" -type f -path '*/result.json' -print -quit 2>/dev/null || true)"
if [[ -n "${RESULT_FILE}" ]]; then
  TRIAL_DIR="$(dirname "${RESULT_FILE}")"
  printf '%s\n' "${TRIAL_DIR}" >"${RUN_DIR}/harbor-source-dir.txt"
  for relative in agent/trajectory.json agent/pi.txt artifacts/logs/artifacts/model.patch \
    artifacts/manifest.json verifier/reward.txt verifier/reward.json result.json \
    exception.txt config.json lock.json trial.log; do
    if [[ -f "${TRIAL_DIR}/${relative}" ]]; then
      mkdir -p "${RUN_DIR}/harbor/$(dirname "${relative}")"
      cp "${TRIAL_DIR}/${relative}" "${RUN_DIR}/harbor/${relative}"
    fi
  done
  find "${TRIAL_DIR}" -maxdepth 8 -type f -print >"${RUN_DIR}/harbor-files.txt"
fi
date --iso-8601=seconds >"${RUN_DIR}/run-body-finished-at.txt"
exit "${HARBOR_EXIT}"
