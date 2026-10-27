#!/usr/bin/env bash
#SBATCH --job-name=fm-word2vec-openhands
#SBATCH --partition=gpu
#SBATCH --constraint=a6000ada
#SBATCH --gres=gpu:1
#SBATCH --cpus-per-task=8
#SBATCH --mem=48G
#SBATCH --time=00:40:00
#SBATCH --output=logs/word2vec-openhands-%j.out
#SBATCH --error=logs/word2vec-openhands-%j.err
set -euo pipefail
cd /home/csgrad/vbork001/frontiermemory-experiment-20261024
export PATH="${PWD}/bin:${PATH}"
export APPTAINER_CACHEDIR="${PWD}/containers/apptainer-cache"
OLLAMA_CONTEXT_LENGTH="${OLLAMA_CONTEXT_LENGTH:-65536}"
REASONING_EFFORT="${REASONING_EFFORT:-medium}"
EXPECTED_GPU="${EXPECTED_GPU:-NVIDIA RTX 6000 Ada Generation}"
export OLLAMA_CONTEXT_LENGTH OLLAMA_KEEP_ALIVE=20m OLLAMA_HOST=127.0.0.1:11434 OLLAMA_MODELS=/models OLLAMA_MAX_LOADED_MODELS=1 OLLAMA_NUM_PARALLEL=1
CONDITION="${CONDITION:-A}"
if [[ "${CONDITION}" != A && "${CONDITION}" != B ]]; then echo "CONDITION must be A or B" >&2; exit 2; fi
MODEL="${MODEL:-qwen3.8:27b-mtp-q4_K_M}"
MODEL_API_NAME="openai/${MODEL}"
MODEL_SLUG="${MODEL//:/-}"
LITELLM_EXTRA_BODY="$(.venv/bin/python -c 'import json,sys; print(json.dumps({"reasoning_effort":sys.argv[1]}))' "${REASONING_EFFORT}")"
MODEL_STORE="/home/csgrad/vbork001/shared-mem-gov-pilot/models"
OLLAMA_SIF="${PWD}/containers/ollama.sif"
AGENT_SIF="${PWD}/containers/frontier-memory-word2vec-agent.sif"
VERIFIER_SIF="${PWD}/containers/frontier-memory-word2vec-verifier.sif"
SOURCE_TASK="${PWD}/data/tasks/frontier-memory/build-word2vec-pipeline"
TASK_PATH="${PWD}/build/word2vec-apptainer/${CONDITION}/job-${SLURM_JOB_ID}/build-word2vec-pipeline"
RUN_DIR="${PWD}/results/word2vec-openhands/${CONDITION}/job-${SLURM_JOB_ID}"
PROMPT_TEMPLATE="${RUN_DIR}/prompt-template.j2"
MEMORY_FILE="${MEMORY_FILE:-}"
HARBOR_JOB_NAME="frontiermemory-word2vec-${MODEL_SLUG}-${CONDITION}-${SLURM_JOB_ID}"
if [[ "${CONDITION}" == B ]]; then test -s "${MEMORY_FILE}"; fi
MODEL_MANIFEST="${MODEL_STORE}/manifests/registry.ollama.ai/library/${MODEL%%:*}/${MODEL##*:}"
if [[ ! -s "${MODEL_MANIFEST}" ]]; then
  echo "Model ${MODEL} is not fully cached at ${MODEL_STORE}; refusing to start a GPU job or download weights." >&2
  exit 3
fi
test -s "${OLLAMA_SIF}" && test -s "${AGENT_SIF}" && test -s "${VERIFIER_SIF}" && test -d "${MODEL_STORE}"
mkdir -p "${RUN_DIR}/ollama" logs
date --iso-8601=seconds >"${RUN_DIR}/started-at.txt"
scontrol show job "${SLURM_JOB_ID}" >"${RUN_DIR}/slurm-job.txt"
nvidia-smi -q >"${RUN_DIR}/nvidia-smi.txt"
nvidia-smi --query-gpu=name,memory.total,memory.free --format=csv >"${RUN_DIR}/gpu.csv"
grep -Fq "${EXPECTED_GPU}" "${RUN_DIR}/gpu.csv"
.venv/bin/harbor --version >"${RUN_DIR}/harbor-version.txt"
apptainer version >"${RUN_DIR}/apptainer-version.txt"
apptainer exec --fakeroot "${OLLAMA_SIF}" ollama --version >"${RUN_DIR}/ollama-version.txt" 2>&1
.venv/bin/python scripts/stage_word2vec_task_for_apptainer.py --source "${SOURCE_TASK}" --output "${TASK_PATH}" --agent-image "${AGENT_SIF}" --verifier-image "${VERIFIER_SIF}" >"${RUN_DIR}/task-staging.json"
cp configs/openhands-word2vec-base-template.j2 "${PROMPT_TEMPLATE}"
if [[ "${CONDITION}" == B ]]; then printf '\n\n## Historical experience memory\n\n' >>"${PROMPT_TEMPLATE}"; cat "${MEMORY_FILE}" >>"${PROMPT_TEMPLATE}"; sha256sum "${MEMORY_FILE}" >"${RUN_DIR}/memory-sha256.txt"; fi
sha256sum "${PROMPT_TEMPLATE}" >"${RUN_DIR}/prompt-template-sha256.txt"
printf '%s\n' "${MODEL}" >"${RUN_DIR}/model.txt"
printf '%s\n' "${OLLAMA_CONTEXT_LENGTH}" >"${RUN_DIR}/requested-context.txt"
printf '%s\n' "${REASONING_EFFORT}" >"${RUN_DIR}/reasoning-effort.txt"
printf '%s\n' "${LITELLM_EXTRA_BODY}" >"${RUN_DIR}/litellm-extra-body.json"
VENV_SOURCE="${PWD}/runtime/openhands-sdk-venv"
PYTHON_SOURCE="${PWD}/runtime/uv/python/cpython-3.12-linux-x86_64-gnu"
test -x "${VENV_SOURCE}/bin/python" && test -x "${PYTHON_SOURCE}/bin/python3.12"
# Harbor's Singularity bootstrap insists on /usr/bin/python3 and creates its
# own /opt/harbor-server venv. Reuse the already-installed OpenHands venv and
# standalone Python through binds, so neither package installation nor image
# rebuild is needed inside the task container.
MOUNTS_JSON="$(.venv/bin/python -c 'import json,sys; v,p=sys.argv[1:]; print(json.dumps([{"type":"bind","source":v,"target":"/opt/openhands-sdk-venv"},{"type":"bind","source":p,"target":p},{"type":"bind","source":v,"target":"/opt/harbor-server"},{"type":"bind","source":p+"/bin/python3.12","target":"/usr/bin/python3"}]))' "${VENV_SOURCE}" "${PYTHON_SOURCE}")"
printf '%s\n' "${MOUNTS_JSON}" >"${RUN_DIR}/environment-mounts.json"
apptainer exec --fakeroot --writable-tmpfs --containall --no-mount home,tmp,bind-paths --bind "${VENV_SOURCE}:/opt/openhands-sdk-venv" --bind "${VENV_SOURCE}:/opt/harbor-server" --bind "${PYTHON_SOURCE}:${PYTHON_SOURCE}" --bind "${PYTHON_SOURCE}/bin/python3.12:/usr/bin/python3" "${AGENT_SIF}" /bin/bash -c '/usr/bin/python3 --version && /opt/harbor-server/bin/python3 -c "import fastapi,uvicorn; print(\"harbor-server-runtime\",fastapi.__version__,uvicorn.__version__)" && /opt/openhands-sdk-venv/bin/python -c "import openhands.sdk, openhands.tools; print(\"openhands-sdk\", openhands.sdk.__version__)"' >"${RUN_DIR}/openhands-runtime-preflight.txt" 2>&1
COMMON_ARGS=(--path "${TASK_PATH}" --env singularity --mounts-json "${MOUNTS_JSON}" --jobs-dir jobs --job-name "${HARBOR_JOB_NAME}" --agent openhands-sdk --model "${MODEL_API_NAME}" --agent-kwarg "prompt_template_path=${PROMPT_TEMPLATE}" --agent-kwarg "reasoning_effort=${REASONING_EFFORT}" --agent-kwarg temperature=0.1 --agent-kwarg load_skills=false --agent-kwarg max_iterations=30 --agent-kwarg python_version=3.12 --agent-env LLM_API_KEY=local-ollama-no-auth --agent-env LLM_BASE_URL=http://127.0.0.1:11434/v1 --agent-env "LITELLM_EXTRA_BODY=${LITELLM_EXTRA_BODY}" --n-attempts 1 --n-concurrent 1 --agent-timeout-multiplier 1.0 --agent-setup-timeout-multiplier 0.5 --yes)
.venv/bin/harbor run "${COMMON_ARGS[@]}" --print-config >"${RUN_DIR}/harbor-resolved-config.json" 2>"${RUN_DIR}/harbor-config.log"
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
set +e
timeout --signal=INT --kill-after=20s 1200s .venv/bin/harbor run "${COMMON_ARGS[@]}" >"${RUN_DIR}/harbor.log" 2>&1
HARBOR_EXIT=$?
set -e
printf '%s\n' "${HARBOR_EXIT}" >"${RUN_DIR}/harbor-exit-code.txt"
curl --fail --silent http://127.0.0.1:11434/api/ps >"${RUN_DIR}/ollama/loaded-model-after-agent.json" || true
if [[ -d "jobs/${HARBOR_JOB_NAME}" ]]; then TRIAL_DIR="$(find "jobs/${HARBOR_JOB_NAME}" -mindepth 1 -maxdepth 1 -type d | head -n 1)"; if [[ -n "${TRIAL_DIR}" ]]; then printf '%s\n' "${TRIAL_DIR}" >"${RUN_DIR}/harbor-source-dir.txt"; cp -a "${TRIAL_DIR}" "${RUN_DIR}/harbor-trial"; fi; fi
.venv/bin/python - "${RUN_DIR}/ollama/tmp" "${RUN_DIR}/ollama/request-parameter-audit.json" "${REASONING_EFFORT}" <<'PY'
import json, pathlib, sys
root = pathlib.Path(sys.argv[1])
files = list(root.rglob("*_body.json"))
matches = []
agent_matches = []
for path in files:
    try:
        body = json.loads(path.read_text(encoding="utf-8", errors="replace"))
    except (OSError, json.JSONDecodeError):
        continue
    if body.get("reasoning_effort") == sys.argv[3]:
        matches.append(str(path.relative_to(root)))
        if body.get("tools"):
            agent_matches.append(str(path.relative_to(root)))
out = {"ollama_request_bodies": len(files), "requests_with_configured_reasoning_effort": matches, "openhands_tool_requests_with_configured_effort": agent_matches, "setting_observed_in_ollama_requests": bool(matches), "agent_request_setting_observed": bool(agent_matches)}
pathlib.Path(sys.argv[2]).write_text(json.dumps(out, indent=2) + "\n", encoding="utf-8")
PY
date --iso-8601=seconds >"${RUN_DIR}/run-body-finished-at.txt"
exit "${HARBOR_EXIT}"
