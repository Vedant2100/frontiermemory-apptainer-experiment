#!/usr/bin/env bash
#SBATCH --job-name=fm-opencode-coding-tasks
#SBATCH --partition=vcggpu
#SBATCH --constraint=rtx3090
#SBATCH --gres=gpu:1
#SBATCH --cpus-per-task=8
#SBATCH --mem=48G
#SBATCH --time=03:00:00
#SBATCH --output=logs/opencode-frontiermemory-%j.out
#SBATCH --error=logs/opencode-frontiermemory-%j.err

set -euo pipefail
cd /home/csgrad/vbork001/frontiermemory-experiment-20261024

export PATH="${PWD}/bin:${PATH}"
export APPTAINER_CACHEDIR="${PWD}/containers/apptainer-cache"
export OLLAMA_CONTEXT_LENGTH=32768
export OLLAMA_KEEP_ALIVE=20m
export OLLAMA_HOST=127.0.0.1:11434
export OLLAMA_MODELS=/models
export TERM=xterm-256color

CONDITION="${CONDITION:?Set CONDITION=A or CONDITION=B}"
case "${CONDITION}" in A|B) ;; *) echo "CONDITION must be A or B" >&2; exit 2 ;; esac
TASK_IDS="${TASK_IDS:?Set colon-separated TASK_IDS}"
MODEL="${MODEL:-qwen3-coder:30b}"
EXPECTED_GPU_REGEX="${EXPECTED_GPU_REGEX:-GeForce RTX 3090}"
MODEL_SLUG="${MODEL//:/-}"
ATTEMPTS="${ATTEMPTS:-1}"
PROMPT_PROFILE="${PROMPT_PROFILE:-paired}"
NO_PROGRESS_STEPS="${NO_PROGRESS_STEPS:-8}"
AGENT_TIMEOUT_MULTIPLIER="${AGENT_TIMEOUT_MULTIPLIER:-1.0}"
MODEL_STORE=/home/csgrad/vbork001/shared-mem-gov-pilot/models
OLLAMA_SIF="${PWD}/containers/ollama.sif"
BASE_CONFIG="${BASE_CONFIG:-${PWD}/configs/opencode-qwen3-coder-30b-A.yaml}"
TASK_ROOT="${PWD}/build/opencode-frontiermemory-tasks"
RUN_DIR="${PWD}/results/opencode-frontiermemory-tasks/job-${SLURM_JOB_ID}-${CONDITION}"

if ! [[ "${ATTEMPTS}" =~ ^[1-9][0-9]*$ ]]; then
  echo "ATTEMPTS must be a positive integer" >&2
  exit 2
fi

mkdir -p "${RUN_DIR}/ollama"
date --iso-8601=seconds >"${RUN_DIR}/started-at.txt"
scontrol show job "${SLURM_JOB_ID}" >"${RUN_DIR}/slurm-job.txt"
nvidia-smi -q >"${RUN_DIR}/nvidia-smi.txt"
nvidia-smi --query-gpu=name,memory.total,memory.free --format=csv >"${RUN_DIR}/gpu.csv"
printf '%s\n' "${EXPECTED_GPU_REGEX}" >"${RUN_DIR}/expected-gpu-regex.txt"
grep -Eq "${EXPECTED_GPU_REGEX}" "${RUN_DIR}/gpu.csv"
.venv/bin/harbor --version >"${RUN_DIR}/harbor-version.txt"
apptainer version >"${RUN_DIR}/apptainer-version.txt"
rg --version >"${RUN_DIR}/host-ripgrep-version.txt"
apptainer exec --fakeroot "${OLLAMA_SIF}" ollama --version >"${RUN_DIR}/ollama-version.txt" 2>&1
printf '%s\n' "${MODEL}" >"${RUN_DIR}/model.txt"
printf '%s\n' "${OLLAMA_CONTEXT_LENGTH}" >"${RUN_DIR}/requested-context.txt"

test -f "${OLLAMA_SIF}"
test -d "${MODEL_STORE}"

if [[ "${CONDITION}" == "B" ]]; then
  MEMORY_PATH="${PWD}/results/frozen-memory-v1/MEMORY.md"
  test -s "${MEMORY_PATH}"
  sha256sum "${MEMORY_PATH}" >"${RUN_DIR}/frozen-memory.sha256"
else
  MEMORY_PATH=""
fi

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
curl --fail --silent http://127.0.0.1:11434/api/tags >"${RUN_DIR}/ollama/tags-before.json"
if ! grep -q "${MODEL}" "${RUN_DIR}/ollama/tags-before.json"; then
  apptainer exec --fakeroot --nv \
    --bind "${MODEL_STORE}:/models" \
    --env OLLAMA_MODELS=/models \
    --env OLLAMA_HOST=127.0.0.1:11434 \
    "${OLLAMA_SIF}" ollama pull "${MODEL}" >"${RUN_DIR}/ollama/pull.log" 2>&1
fi
curl --fail --silent http://127.0.0.1:11434/api/tags >"${RUN_DIR}/ollama/tags.json"
grep -q "${MODEL}" "${RUN_DIR}/ollama/tags.json"
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

run_task() {
  local task_id="$1"
  local attempt="$2"
  local task_path="${TASK_ROOT}/${task_id}"
  local task_dir="${RUN_DIR}/${task_id}/attempt-${attempt}"
  local harbor_job_name="frontiermemory-v1.0-${task_id}-opencode-${MODEL_SLUG}-${CONDITION}-${SLURM_JOB_ID}-attempt-${attempt}"
  local harbor_pid watch_pid harbor_exit
  mkdir -p "${task_dir}"
  test -f "${task_path}/task.toml"
  test -f "${task_path}/apptainer-adaptation.json"
  python3 - "${task_path}/apptainer-adaptation.json" "${task_dir}" <<'PY'
import json
import subprocess
import sys
from pathlib import Path

adaptation = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
task_dir = Path(sys.argv[2])
for key, output_name in (
    ("apptainer_image", "agent-ripgrep-version.txt"),
    ("verifier_apptainer_image", "verifier-ripgrep-version.txt"),
):
    image = adaptation[key]
    result = subprocess.run(
        ["bin/singularity", "exec", image, "rg", "--version"],
        check=True,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )
    (task_dir / output_name).write_text(result.stdout, encoding="utf-8")
PY

  local -a prompt_args=(
    --base-config "${BASE_CONFIG}"
    --profile "${PROMPT_PROFILE}"
    --prompt-template "${task_dir}/prompt-template.md"
    --output-config "${task_dir}/opencode.yaml"
  )
  if [[ -n "${MEMORY_PATH}" ]]; then
    prompt_args+=(--memory "${MEMORY_PATH}")
  fi
  .venv/bin/python scripts/render_opencode_memory_config.py "${prompt_args[@]}" \
    >"${task_dir}/prompt-render.log" 2>&1

  set +e
  .venv/bin/harbor run \
    --config "${task_dir}/opencode.yaml" \
    --path "${task_path}" \
    --env singularity \
    --jobs-dir jobs \
    --job-name "${harbor_job_name}" \
    --n-attempts 1 \
    --n-concurrent 1 \
    --agent-timeout-multiplier "${AGENT_TIMEOUT_MULTIPLIER}" \
    --yes >"${task_dir}/harbor.log" 2>&1 &
  harbor_pid=$!
  python3 scripts/watch_harbor_opencode.py \
    --jobs-dir jobs \
    --job-name "${harbor_job_name}" \
    --harbor-pid "${harbor_pid}" \
    --marker "${task_dir}/repetition-stop.json" \
    --no-progress-steps "${NO_PROGRESS_STEPS}" \
    >"${task_dir}/watch.log" 2>&1 &
  watch_pid=$!
  wait "${harbor_pid}"
  harbor_exit=$?
  wait "${watch_pid}" 2>/dev/null
  set -e
  printf '%s\n' "${harbor_exit}" >"${task_dir}/harbor-exit-code.txt"

  local trial_dir=""
  if [[ -d "jobs/${harbor_job_name}" ]]; then
    trial_dir="$(find "jobs/${harbor_job_name}" -mindepth 1 -maxdepth 1 -type d | head -n 1)"
  fi
  if [[ -n "${trial_dir}" ]]; then
    for relative in agent/trajectory.json agent/opencode.txt artifacts/logs/artifacts/model.patch \
      artifacts/manifest.json verifier/reward.txt verifier/reward.json result.json exception.txt \
      config.json lock.json trial.log; do
      if [[ -f "${trial_dir}/${relative}" ]]; then
        mkdir -p "${task_dir}/harbor/$(dirname "${relative}")"
        cp "${trial_dir}/${relative}" "${task_dir}/harbor/${relative}"
      fi
    done
    printf '%s\n' "${trial_dir}" >"${task_dir}/harbor-source-dir.txt"
    find "${trial_dir}" -maxdepth 8 -type f -print >"${task_dir}/harbor-files.txt"
  fi
}

IFS=':' read -r -a TASK_ARRAY <<<"${TASK_IDS}"
for task_id in "${TASK_ARRAY[@]}"; do
  for attempt in $(seq 1 "${ATTEMPTS}"); do
    run_task "${task_id}" "${attempt}"
  done
done

curl --fail --silent http://127.0.0.1:11434/api/ps >"${RUN_DIR}/ollama/loaded-model-at-end.json" || true
curl --fail --silent http://127.0.0.1:11434/api/tags >"${RUN_DIR}/ollama/tags-after.json" || true
date --iso-8601=seconds >"${RUN_DIR}/run-body-finished-at.txt"
