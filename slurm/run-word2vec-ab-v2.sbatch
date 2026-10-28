#!/usr/bin/env bash
#SBATCH --job-name=fm-word2vec-ab-v2
#SBATCH --partition=vcggpu
#SBATCH --constraint=rtx3090
#SBATCH --gres=gpu:2
#SBATCH --cpus-per-task=8
#SBATCH --mem=96G
#SBATCH --time=04:00:00
#SBATCH --output=logs/word2vec-ab-v2-%j.out
#SBATCH --error=logs/word2vec-ab-v2-%j.err
# Protocol v2 (Phase 3 smoke and Phase 4 A/B). One Ollama server and one model load for the
# whole job; trials run sequentially in TRIAL_ORDER. Each trial gets a fresh staged task copy,
# a fresh persistent workspace, and a unique Harbor job name. The task's own 1200 s agent
# timeout is the only per-trial stop rule; there are no manual mid-trial kills.
set -euo pipefail
cd /home/csgrad/vbork001/frontiermemory-experiment-20261024
export PATH="${PWD}/bin:${PATH}"
export APPTAINER_CACHEDIR="${PWD}/containers/apptainer-cache"
OLLAMA_CONTEXT_LENGTH="${OLLAMA_CONTEXT_LENGTH:-65536}"
REASONING_EFFORT="${REASONING_EFFORT:-medium}"
EXPECTED_GPU="${EXPECTED_GPU:-NVIDIA GeForce RTX 3090}"
export OLLAMA_CONTEXT_LENGTH OLLAMA_KEEP_ALIVE=20m OLLAMA_HOST=127.0.0.1:11434 OLLAMA_MODELS=/models OLLAMA_MAX_LOADED_MODELS=1 OLLAMA_NUM_PARALLEL=1
MODEL="${MODEL:-qwen3.8:27b-mtp-q4_K_M}"
MODEL_API_NAME="openai/${MODEL}"
MODEL_SLUG="${MODEL//:/-}"
LITELLM_EXTRA_BODY="$(.venv/bin/python -c 'import json,sys; print(json.dumps({"reasoning_effort":sys.argv[1]}))' "${REASONING_EFFORT}")"
MODEL_STORE="/home/csgrad/vbork001/shared-mem-gov-pilot/models"
OLLAMA_SIF="${PWD}/containers/ollama.sif"
AGENT_SIF="${PWD}/containers/frontier-memory-word2vec-agent.sif"
VERIFIER_SIF="${PWD}/containers/frontier-memory-word2vec-verifier-harbor-py310.sif"
VERIFIER_BASE_SIF="${PWD}/containers/frontier-memory-word2vec-verifier.sif"
VERIFIER_DEF="${PWD}/containers/frontier-memory-word2vec-verifier-harbor.def"
SOURCE_TASK="${PWD}/data/tasks/frontier-memory/build-word2vec-pipeline"
VENV_SOURCE="${PWD}/runtime/openhands-sdk-venv"
PYTHON_SOURCE="${PWD}/runtime/uv/python/cpython-3.12-linux-x86_64-gnu"
HARBOR_SHARED_BINDPATH="${PYTHON_SOURCE}:${PYTHON_SOURCE},${VENV_SOURCE}:/opt/harbor-server"
BASE_TEMPLATE_SOURCE="${PWD}/configs/openhands-word2vec-base-template.j2"
HELPER="${PWD}/scripts/word2vec_ab_v2_records.py"
# Harbor 0.24.0 Singularity exec timeout correction (see protocol-v2.md amendment 2026-10-27).
# Runs the Harbor CLI with a default exec timeout so the task agent timeout, not a hard 600 s HTTP cap, binds.
HARBOR_WRAPPER="${PWD}/scripts/harbor_singularity_exec_timeout.py"
export HARBOR_SINGULARITY_EXEC_TIMEOUT_SEC="${HARBOR_SINGULARITY_EXEC_TIMEOUT_SEC:-7200}"

# Protocol v2 knobs. TRIAL_ORDER is a space-separated list of A/B tokens.
TRIAL_ORDER="${TRIAL_ORDER:-A B B A A B}"
MAX_ITERATIONS="${MAX_ITERATIONS:-200}"
AGENT_TIMEOUT_SEC="${AGENT_TIMEOUT_SEC:-1200}"
TRIAL_HANG_GUARD="${TRIAL_HANG_GUARD:-2400s}"
FROZEN_MEMORY="${FROZEN_MEMORY:-${PWD}/memory/frozen-v2/MEMORY.md}"
EXPECTED_MEMORY_SHA256="${EXPECTED_MEMORY_SHA256:-eb044c32ec3246f474cb0dbfa57f3cdbe8d5ddb93f691648eb65ed95b6a578ab}"

read -r -a TRIAL_TOKENS <<<"${TRIAL_ORDER}"
if [[ "${#TRIAL_TOKENS[@]}" -lt 1 ]]; then echo "TRIAL_ORDER is empty" >&2; exit 2; fi
for token in "${TRIAL_TOKENS[@]}"; do
  if [[ "${token}" != A && "${token}" != B ]]; then echo "TRIAL_ORDER token must be A or B: ${token}" >&2; exit 2; fi
done
if [[ "${MAX_ITERATIONS}" != 200 && -z "${ALLOW_NONSTANDARD_MAX_ITERATIONS:-}" ]]; then
  echo "Protocol v2 fixes MAX_ITERATIONS=200; set ALLOW_NONSTANDARD_MAX_ITERATIONS=1 to override for diagnostics." >&2
  exit 2
fi

RUN_DIR="${PWD}/results/word2vec-openhands/ab-v2/job-${SLURM_JOB_ID}"
BUILD_ROOT="${PWD}/build/word2vec-apptainer/ab-v2/job-${SLURM_JOB_ID}"
MANIFEST_NAME="registry.ollama.ai/library/${MODEL%%:*}/${MODEL##*:}"
MODEL_MANIFEST="${MODEL_STORE}/manifests/${MANIFEST_NAME}"

# Fail before any trial: frozen memory must be present and match the pinned hash.
# Checked unconditionally so a bad memory file can never reach a B trial.
test -s "${FROZEN_MEMORY}"
ACTUAL_MEMORY_SHA="$(sha256sum "${FROZEN_MEMORY}" | awk '{print $1}')"
if [[ "${ACTUAL_MEMORY_SHA}" != "${EXPECTED_MEMORY_SHA256}" ]]; then
  echo "Frozen memory sha256 mismatch; aborting before any trial." >&2
  exit 4
fi

if [[ ! -s "${MODEL_MANIFEST}" ]]; then
  echo "Model ${MODEL} is not fully cached at ${MODEL_STORE}; refusing to start a GPU job or download weights." >&2
  exit 3
fi
test -s "${OLLAMA_SIF}" && test -s "${AGENT_SIF}" && test -s "${VERIFIER_BASE_SIF}" && test -s "${VERIFIER_DEF}" && test -d "${MODEL_STORE}"
test -s "${BASE_TEMPLATE_SOURCE}" && test -s "${HELPER}" && test -s "${HARBOR_WRAPPER}" && test -d "${SOURCE_TASK}"
mkdir -p "${RUN_DIR}/ollama" "${RUN_DIR}/preflight" "${BUILD_ROOT}" logs
date --iso-8601=seconds >"${RUN_DIR}/started-at.txt"
printf '%s\n' "${TRIAL_ORDER}" >"${RUN_DIR}/trial-order.txt"
printf '%s\n' "${MAX_ITERATIONS}" >"${RUN_DIR}/max-iterations.txt"
printf '%s\n' "${AGENT_TIMEOUT_SEC}" >"${RUN_DIR}/agent-timeout-sec.txt"
sha256sum "${HARBOR_WRAPPER}" >"${RUN_DIR}/harbor-wrapper-sha256.txt"
printf 'HARBOR_SINGULARITY_EXEC_TIMEOUT_SEC=%s\n' "${HARBOR_SINGULARITY_EXEC_TIMEOUT_SEC}" >"${RUN_DIR}/harbor-exec-timeout.txt"
printf '%s  %s\n' "${ACTUAL_MEMORY_SHA}" "${FROZEN_MEMORY}" >"${RUN_DIR}/frozen-memory-sha256.txt"
scontrol show job "${SLURM_JOB_ID}" >"${RUN_DIR}/slurm-job.txt"
nvidia-smi -q >"${RUN_DIR}/nvidia-smi.txt"
nvidia-smi --query-gpu=name,memory.total,memory.free --format=csv >"${RUN_DIR}/gpu.csv"
grep -Fq "${EXPECTED_GPU}" "${RUN_DIR}/gpu.csv"
printf 'CUDA_VISIBLE_DEVICES=%s\nSLURM_JOB_GPUS=%s\n' "${CUDA_VISIBLE_DEVICES:-unset}" "${SLURM_JOB_GPUS:-unset}" >"${RUN_DIR}/gpu-allocation.txt"
.venv/bin/harbor --version >"${RUN_DIR}/harbor-version.txt"
apptainer version >"${RUN_DIR}/apptainer-version.txt"
apptainer exec --fakeroot "${OLLAMA_SIF}" ollama --version >"${RUN_DIR}/ollama-version.txt" 2>&1
sha256sum "${SOURCE_TASK}/tests/test.sh" "${SOURCE_TASK}/tests/test_outputs.py" >"${RUN_DIR}/verifier-source-sha256.txt"
if [[ ! -s "${VERIFIER_SIF}" ]]; then
  apptainer build --fakeroot "${VERIFIER_SIF}" "${VERIFIER_DEF}" >"${RUN_DIR}/verifier-image-build.log" 2>&1
fi
test -s "${VERIFIER_SIF}"
apptainer exec --fakeroot --pwd /tests "${VERIFIER_SIF}" /bin/bash -lc 'test -s /tests/test.sh && test -s /tests/test_outputs.py && /usr/bin/python3 -c "import sys,gensim,nltk,numpy,pytest,scipy; assert sys.version_info[:2] == (3,10), sys.version; print(\"verifier-python\",sys.version.split()[0])"' >"${RUN_DIR}/verifier-image-preflight.txt" 2>&1
apptainer exec --fakeroot --pwd /tests "${VERIFIER_SIF}" sha256sum /tests/test.sh /tests/test_outputs.py >"${RUN_DIR}/verifier-image-tests-sha256.txt"
.venv/bin/python - "${RUN_DIR}/verifier-source-sha256.txt" "${RUN_DIR}/verifier-image-tests-sha256.txt" <<'PY'
import pathlib, sys
source, image = (pathlib.Path(path) for path in sys.argv[1:])
source_hashes = [line.split()[0] for line in source.read_text().splitlines()]
image_hashes = [line.split()[0] for line in image.read_text().splitlines()]
if source_hashes != image_hashes or len(source_hashes) != 2:
    raise SystemExit("Verifier SIF test files differ from the pinned task source")
PY
printf '%s\n' "${HARBOR_SHARED_BINDPATH}" >"${RUN_DIR}/apptainer-shared-bindpath.txt"
APPTAINER_BINDPATH="${HARBOR_SHARED_BINDPATH}" SINGULARITY_BINDPATH="${HARBOR_SHARED_BINDPATH}" apptainer exec --no-mount home,tmp,bind-paths --pwd /tests --writable-tmpfs --fakeroot --containall --pid "${VERIFIER_SIF}" /bin/bash -c '/usr/bin/python3 -c "import sys,gensim,nltk,numpy,pytest,scipy; assert sys.version_info[:2] == (3,10), sys.version; print(\"verifier-python\",sys.version.split()[0])" && /opt/harbor-server/bin/python3 -c "import fastapi,uvicorn; print(\"harbor-server-runtime\",fastapi.__version__,uvicorn.__version__)"' >"${RUN_DIR}/verifier-runtime-preflight.txt" 2>&1
sha256sum "${VERIFIER_SIF}" >"${RUN_DIR}/verifier-image-sha256.txt"
apptainer exec --fakeroot --writable-tmpfs --containall --no-mount home,tmp,bind-paths --bind "${PYTHON_SOURCE}/bin/python3.12:/usr/bin/python3" --pwd /workspace "${AGENT_SIF}" /bin/bash -c '/usr/bin/python3 --version' >"${RUN_DIR}/agent-runtime-preflight.txt" 2>&1

# Shared task-metadata preflight and base prompt header (identical for every trial of this job).
PREFLIGHT_TASK="${BUILD_ROOT}/preflight/build-word2vec-pipeline"
.venv/bin/python scripts/stage_word2vec_task_for_apptainer.py --source "${SOURCE_TASK}" --output "${PREFLIGHT_TASK}" --agent-image "${AGENT_SIF}" --verifier-image "${VERIFIER_SIF}" >"${RUN_DIR}/preflight/task-staging.json"
.venv/bin/python "${HELPER}" check-task --task-toml "${PREFLIGHT_TASK}/task.toml" --staging "${RUN_DIR}/preflight/task-staging.json" --output "${RUN_DIR}/preflight/staged-task-preflight.json"
BASE_TEMPLATE="${RUN_DIR}/base-prompt-template.j2"
.venv/bin/python "${HELPER}" base-template --metadata "${RUN_DIR}/preflight/staged-task-preflight.json" --template "${BASE_TEMPLATE_SOURCE}" --output "${BASE_TEMPLATE}"
BASE_SHA="$(sha256sum "${BASE_TEMPLATE}" | awk '{print $1}')"
printf '%s  %s\n' "${BASE_SHA}" "${BASE_TEMPLATE}" >"${RUN_DIR}/base-prompt-template-sha256.txt"

# Python 3.12 agent runtime and Harbor venv presence (same binds as the existing runner).
test -x "${VENV_SOURCE}/bin/python" && test -x "${PYTHON_SOURCE}/bin/python3.12"

# Ollama: one server and one model load for the whole job.
mkdir -p "${RUN_DIR}/ollama/tmp"
apptainer exec --fakeroot --nv --bind "${MODEL_STORE}:/models" --bind "${RUN_DIR}/ollama:/ollama-logs" --env OLLAMA_MODELS=/models --env OLLAMA_HOST=127.0.0.1:11434 --env OLLAMA_CONTEXT_LENGTH="${OLLAMA_CONTEXT_LENGTH}" --env OLLAMA_KEEP_ALIVE="${OLLAMA_KEEP_ALIVE}" --env OLLAMA_MAX_LOADED_MODELS="${OLLAMA_MAX_LOADED_MODELS}" --env OLLAMA_NUM_PARALLEL="${OLLAMA_NUM_PARALLEL}" --env OLLAMA_DEBUG_LOG_REQUESTS=true --env TMPDIR=/ollama-logs/tmp "${OLLAMA_SIF}" ollama serve >"${RUN_DIR}/ollama/server.log" 2>&1 &
SERVER_PID=$!
cleanup() { if [[ -n "${SERVER_PID:-}" ]]; then kill "${SERVER_PID}" 2>/dev/null || true; wait "${SERVER_PID}" 2>/dev/null || true; fi; date --iso-8601=seconds >"${RUN_DIR}/finished-at.txt"; }
trap cleanup EXIT
READY=0
for attempt in $(seq 1 60); do if curl --fail --silent http://127.0.0.1:11434/api/version >"${RUN_DIR}/ollama/api-version.json"; then READY=1; break; fi; sleep 2; done
test "${READY}" = 1
curl --fail --silent http://127.0.0.1:11434/api/tags >"${RUN_DIR}/ollama/tags-before.json"
if ! grep -Fq "${MODEL}" "${RUN_DIR}/ollama/tags-before.json"; then
  echo "Model ${MODEL} is absent from Ollama tags; refusing to download weights inside the evaluation job." >&2
  exit 3
fi
cp "${RUN_DIR}/ollama/tags-before.json" "${RUN_DIR}/ollama/tags.json"
curl --fail --silent --show-error http://127.0.0.1:11434/api/chat -H 'Content-Type: application/json' -d "{\"model\":\"${MODEL}\",\"stream\":false,\"think\":true,\"reasoning_effort\":\"${REASONING_EFFORT}\",\"messages\":[{\"role\":\"user\",\"content\":\"Think briefly about 2+2, then reply READY.\"}],\"options\":{\"num_ctx\":${OLLAMA_CONTEXT_LENGTH},\"num_predict\":64,\"temperature\":0}}" >"${RUN_DIR}/ollama/smoke-response.json"
curl --fail --silent --show-error http://127.0.0.1:11434/v1/chat/completions -H 'Content-Type: application/json' -H 'Authorization: Bearer local-ollama-no-auth' -d "{\"model\":\"${MODEL}\",\"messages\":[{\"role\":\"user\",\"content\":\"Reply READY.\"}],\"reasoning_effort\":\"${REASONING_EFFORT}\",\"max_tokens\":64,\"temperature\":0}" >"${RUN_DIR}/ollama/openai-reasoning-smoke.json"
.venv/bin/python - "${RUN_DIR}/ollama/smoke-response.json" "${RUN_DIR}/ollama/openai-reasoning-smoke.json" "${REASONING_EFFORT}" >"${RUN_DIR}/ollama/reasoning-smoke-summary.json" <<'PY'
import json, sys
native = json.load(open(sys.argv[1], encoding="utf-8"))
compat = json.load(open(sys.argv[2], encoding="utf-8"))
thinking = native.get("message", {}).get("thinking", "")
if not thinking:
    raise SystemExit("Ollama native API smoke did not return a separate thinking field")
if not compat.get("choices"):
    raise SystemExit("Ollama OpenAI-compatible reasoning smoke returned no choice")
print(json.dumps({"native_thinking_field_nonempty": True, "native_thinking_chars": len(thinking), "openai_compatible_request_completed": True, "requested_reasoning_effort": sys.argv[3]}, indent=2))
PY
curl --fail --silent http://127.0.0.1:11434/api/ps >"${RUN_DIR}/ollama/loaded-model-before-agent.json"
.venv/bin/python -c 'import json,sys; m=json.load(open(sys.argv[1],encoding="utf-8"))["models"][0]; print("name",m.get("name")); print("context_length",m.get("context_length")); print("size_vram",m.get("size_vram")); sys.exit(0 if m.get("context_length")==int(sys.argv[2]) else 1)' "${RUN_DIR}/ollama/loaded-model-before-agent.json" "${OLLAMA_CONTEXT_LENGTH}" >"${RUN_DIR}/ollama/loaded-model-summary.txt"
nvidia-smi --query-gpu=name,memory.used,memory.total --format=csv >"${RUN_DIR}/gpu-after-model-load.csv"

run_trial() {
  local index="$1" condition="$2"
  local tag="trial-${index}-${condition}"
  local tdir="${RUN_DIR}/${tag}"
  local task_path="${BUILD_ROOT}/${tag}/build-word2vec-pipeline"
  local workspace="${tdir}/workspace"
  local job_name="frontiermemory-word2vec-ab-v2-${MODEL_SLUG}-job${SLURM_JOB_ID}-t${index}-${condition}"
  local prompt="${tdir}/prompt-template.j2"
  mkdir -p "${tdir}" "${workspace}"
  chmod 777 "${workspace}"
  touch "${tdir}/trial-start.marker"
  date --iso-8601=seconds >"${tdir}/started-at.txt"
  printf '%s\n' "${job_name}" >"${tdir}/harbor-job-name.txt"

  # Fresh staged task copy and a fresh per-trial preflight.
  .venv/bin/python scripts/stage_word2vec_task_for_apptainer.py --source "${SOURCE_TASK}" --output "${task_path}" --agent-image "${AGENT_SIF}" --verifier-image "${VERIFIER_SIF}" >"${tdir}/task-staging.json"
  .venv/bin/python "${HELPER}" check-task --task-toml "${task_path}/task.toml" --staging "${tdir}/task-staging.json" --output "${tdir}/staged-task-preflight.json"
  sha256sum "${task_path}/task.toml" >"${tdir}/task-toml-sha256.txt"

  # Prompt: identical base template for every trial; B appends exactly the existing memory section.
  local base_now
  base_now="$(sha256sum "${BASE_TEMPLATE}" | awk '{print $1}')"
  if [[ "${base_now}" != "${BASE_SHA}" ]]; then echo "Base prompt template changed mid-job; aborting." >&2; exit 5; fi
  cp "${BASE_TEMPLATE}" "${prompt}"
  if [[ "${condition}" == B ]]; then printf '\n\n## Historical experience memory\n\n' >>"${prompt}"; cat "${FROZEN_MEMORY}" >>"${prompt}"; fi
  local final_sha
  final_sha="$(sha256sum "${prompt}" | awk '{print $1}')"
  printf '%s  %s\n' "${final_sha}" "${prompt}" >"${tdir}/prompt-template-sha256.txt"
  if [[ "${condition}" == B ]]; then printf '%s  %s\n' "${ACTUAL_MEMORY_SHA}" "${FROZEN_MEMORY}" >"${tdir}/memory-sha256.txt"; fi

  local mounts_json
  mounts_json="$(.venv/bin/python -c 'import json,sys; p,w=sys.argv[1:]; print(json.dumps([{"type":"bind","source":p+"/bin/python3.12","target":"/usr/bin/python3"},{"type":"bind","source":w,"target":"/workspace"}]))' "${PYTHON_SOURCE}" "${workspace}")"
  printf '%s\n' "${mounts_json}" >"${tdir}/environment-mounts.json"
  local common_args=(--path "${task_path}" --env singularity --mounts-json "${mounts_json}" --jobs-dir jobs --job-name "${job_name}" --agent openhands-sdk --model "${MODEL_API_NAME}" --agent-kwarg "prompt_template_path=${prompt}" --agent-kwarg "reasoning_effort=${REASONING_EFFORT}" --agent-kwarg temperature=0.1 --agent-kwarg load_skills=false --agent-kwarg "max_iterations=${MAX_ITERATIONS}" --agent-kwarg python_version=3.12 --agent-env LLM_API_KEY=local-ollama-no-auth --agent-env LLM_BASE_URL=http://127.0.0.1:11434/v1 --agent-env "LITELLM_EXTRA_BODY=${LITELLM_EXTRA_BODY}" --n-attempts 1 --n-concurrent 1 --agent-timeout-multiplier 1.0 --agent-setup-timeout-multiplier 0.5 --yes)
  APPTAINER_BINDPATH="${HARBOR_SHARED_BINDPATH}" SINGULARITY_BINDPATH="${HARBOR_SHARED_BINDPATH}" .venv/bin/python "${HARBOR_WRAPPER}" run "${common_args[@]}" --print-config >"${tdir}/harbor-resolved-config.json" 2>"${tdir}/harbor-config.log" || true
  curl --fail --silent http://127.0.0.1:11434/api/ps >"${tdir}/loaded-model-before-trial.json" || true

  # Single official stop rule: Harbor's agent timeout (task.toml 1200 s). The hang guard only
  # protects the cluster job from a wedged container and is not a per-trial stop decision.
  set +e
  APPTAINER_BINDPATH="${HARBOR_SHARED_BINDPATH}" SINGULARITY_BINDPATH="${HARBOR_SHARED_BINDPATH}" timeout --signal=INT --kill-after=60s "${TRIAL_HANG_GUARD}" .venv/bin/python "${HARBOR_WRAPPER}" run "${common_args[@]}" >"${tdir}/harbor.log" 2>&1
  local harbor_exit=$?
  set -e
  printf '%s\n' "${harbor_exit}" >"${tdir}/harbor-exit-code.txt"
  curl --fail --silent http://127.0.0.1:11434/api/ps >"${tdir}/loaded-model-after-trial.json" || true

  local job_dir="jobs/${job_name}"
  if [[ -d "${job_dir}" ]]; then
    local trial_src
    trial_src="$(find "${job_dir}" -mindepth 1 -maxdepth 1 -type d | head -n 1)"
    if [[ -n "${trial_src}" ]]; then
      printf '%s\n' "${trial_src}" >"${tdir}/harbor-source-dir.txt"
      cp -a "${trial_src}" "${tdir}/harbor-trial"
    fi
  fi
  date --iso-8601=seconds >"${tdir}/finished-at.txt"

  # Sanitized per-trial record (counts only).
  .venv/bin/python "${HELPER}" trial-record \
    --trial-dir "${tdir}" --job-dir "${job_dir}" --job-id "${SLURM_JOB_ID}" --job-name "${job_name}" \
    --index "${index}" --condition "${condition}" --harbor-exit "${harbor_exit}" \
    --max-iterations "${MAX_ITERATIONS}" --agent-timeout-sec "${AGENT_TIMEOUT_SEC}" \
    --reasoning-effort "${REASONING_EFFORT}" --base-sha "${BASE_SHA}" --final-sha "${final_sha}" \
    --body-dir "${RUN_DIR}/ollama/tmp" --marker "${tdir}/trial-start.marker"
  echo "trial ${index} condition=${condition} harbor_exit=${harbor_exit}"
}

INDEX=0
for token in "${TRIAL_TOKENS[@]}"; do
  INDEX=$((INDEX + 1))
  run_trial "${INDEX}" "${token}" || echo "trial ${INDEX} (${token}) returned nonzero; record written if possible" >&2
done

.venv/bin/python "${HELPER}" aggregate --run-dir "${RUN_DIR}" --job-id "${SLURM_JOB_ID}" --trial-order "${TRIAL_ORDER}"
date --iso-8601=seconds >"${RUN_DIR}/run-body-finished-at.txt"
