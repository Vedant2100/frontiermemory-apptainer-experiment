#!/usr/bin/env bash
# Codex CLI trial for the Word2Vec task with a LOCAL model: Codex talks to an Ollama server that this
# Slurm GPU job starts itself (qwen3.8:27b-mtp-q4_K_M, num_ctx 65536, reasoning effort medium).
#
# No OpenAI or ChatGPT credentials are used: no auth.json is copied, the container runs with --cleanenv,
# and the Codex provider points at 127.0.0.1 only. Apptainer shares the host network (no --net), so the
# task agent container reaches the host Ollama at 127.0.0.1:<OLLAMA_PORT>.
#
# Memory is seeded the way frontier_memory.agents.codex.MemoryCodex does it: the whole memory folder is
# copied to $CODEX_HOME/memories/, memory_summary.md is that folder's MEMORY.md when it has no
# memory_summary.md of its own, and features.memories is on for A and B. Codex runs with --ephemeral,
# web search off (-c web_search=disabled), and --enable unified_exec, as Harbor's Codex agent does.
#
# Env:
#   TRIAL_ORDER     space-separated A/B tokens (default: A). Condition A has no memory.
#   FROZEN_MEMORY_DIR      memory folder for condition B (required when TRIAL_ORDER has a B).
#   EXPECTED_MEMORY_DIGEST official folder digest the memory must match (required with B).
#   TASK            task name (default build-word2vec-pipeline; the only task with a stager here).
#   OLLAMA_PORT     port for the job's Ollama server (default: a free port picked at start).
#   MODEL, REASONING, OLLAMA_CONTEXT_LENGTH  fixed to qwen3.8:27b-mtp-q4_K_M, medium, 65536.
# Records hold counts, names, and status only. Raw event streams and request bodies stay under results/
# and are git-ignored.
set -euo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "${REPO}"
export PATH="${REPO}/bin:${PATH}"
export APPTAINER_CACHEDIR="${REPO}/containers/apptainer-cache"
PY="${REPO}/.venv/bin/python"

MODEL="${MODEL:-qwen3.8:27b-mtp-q4_K_M}"
REASONING="${REASONING:-medium}"
OLLAMA_CONTEXT_LENGTH="${OLLAMA_CONTEXT_LENGTH:-65536}"
TASK="${TASK:-build-word2vec-pipeline}"
if [[ "${MODEL}" != "qwen3.8:27b-mtp-q4_K_M" ]]; then echo "Only model qwen3.8:27b-mtp-q4_K_M is allowed here." >&2; exit 2; fi
if [[ "${REASONING}" != "medium" ]]; then echo "REASONING must be medium." >&2; exit 2; fi
if [[ "${OLLAMA_CONTEXT_LENGTH}" != "65536" ]]; then echo "OLLAMA_CONTEXT_LENGTH must be 65536." >&2; exit 2; fi
if [[ "${TASK}" != "build-word2vec-pipeline" ]]; then
  echo "TASK ${TASK}: only build-word2vec-pipeline has a stager in this runner." >&2; exit 2
fi

TRIAL_ORDER="${TRIAL_ORDER:-A}"
read -r -a TRIAL_TOKENS <<<"${TRIAL_ORDER}"
if [[ "${#TRIAL_TOKENS[@]}" -lt 1 ]]; then echo "TRIAL_ORDER is empty" >&2; exit 2; fi
HAS_B=0
for token in "${TRIAL_TOKENS[@]}"; do
  case "${token}" in
    A) ;;
    B) HAS_B=1 ;;
    *) echo "TRIAL_ORDER token must be A or B: ${token}" >&2; exit 2 ;;
  esac
done

JOB_ID="${SLURM_JOB_ID:-local-$(date +%Y%m%d%H%M%S)}"
TRIAL_TIMEOUT_SEC="${TRIAL_TIMEOUT_SEC:-1200}"   # task.toml [agent] timeout_sec (official stop rule)
PROBE_TIMEOUT_SEC="${PROBE_TIMEOUT_SEC:-600}"
GRADE_GUARD="${GRADE_GUARD:-1800s}"              # outer hang guard for the grading Harbor call only

# Memory for condition B: a folder, checked against the official digest before any trial starts.
FROZEN_MEMORY_DIR="${FROZEN_MEMORY_DIR:-}"
EXPECTED_MEMORY_DIGEST="${EXPECTED_MEMORY_DIGEST:-}"
if [[ "${HAS_B}" == 1 ]]; then
  if [[ -z "${FROZEN_MEMORY_DIR}" || -z "${EXPECTED_MEMORY_DIGEST}" ]]; then
    echo "TRIAL_ORDER has B: set FROZEN_MEMORY_DIR and EXPECTED_MEMORY_DIGEST." >&2; exit 4
  fi
  test -d "${FROZEN_MEMORY_DIR}"
fi

# Shared base prompt template from the OpenHands A/B job (same bytes as the existing Codex runner).
TEMPLATE_DIR="${REPO}/results/word2vec-openhands/ab-v2/job-301916"
PROMPT_TEMPLATE_SRC="${TEMPLATE_DIR}/base-prompt-template.j2"
EXPECTED_TEMPLATE_SHA="$(awk '{print $1}' "${TEMPLATE_DIR}/base-prompt-template-sha256.txt")"
INSTRUCTION="${REPO}/data/tasks/frontier-memory/build-word2vec-pipeline/instruction.md"

SOURCE_TASK="${REPO}/data/tasks/frontier-memory/${TASK}"
AGENT_SIF="${REPO}/containers/frontier-memory-word2vec-agent.sif"
VERIFIER_SIF="${REPO}/containers/frontier-memory-word2vec-verifier-harbor-py310.sif"
OLLAMA_SIF="${REPO}/containers/ollama.sif"
MODEL_STORE="/home/csgrad/vbork001/shared-mem-gov-pilot/models"
VENV_SOURCE="${REPO}/runtime/openhands-sdk-venv"
PYTHON_SOURCE="${REPO}/runtime/uv/python/cpython-3.12-linux-x86_64-gnu"
HARBOR_SHARED_BINDPATH="${PYTHON_SOURCE}:${PYTHON_SOURCE},${VENV_SOURCE}:/opt/harbor-server"
HARBOR_WRAPPER="${REPO}/scripts/harbor_singularity_exec_timeout.py"
export HARBOR_SINGULARITY_EXEC_TIMEOUT_SEC="${HARBOR_SINGULARITY_EXEC_TIMEOUT_SEC:-7200}"
RECORDS_HELPER="${REPO}/scripts/word2vec_ab_v2_records.py"
CODEX_HELPER="${REPO}/scripts/word2vec_codex_trial.py"
NEW_HELPER="${REPO}/scripts/word2vec_codex_ollama_helper.py"

# Codex CLI install (npm-global package plus Node), as in the existing Codex runner. No auth.json is read.
CODEX_RUNTIME="${CODEX_RUNTIME:-/home/csgrad/vbork001/codex-runtime}"
CODEX_NODE_DIR="$(readlink -f "${CODEX_RUNTIME}/node/current")"
CODEX_NPM_DIR="$(readlink -f "${CODEX_RUNTIME}/npm-global")"

RUN_DIR="${REPO}/results/word2vec-codex-ollama/job-${JOB_ID}"
BUILD_ROOT="${REPO}/build/word2vec-apptainer/codex-ollama/job-${JOB_ID}"

if [[ -z "${OLLAMA_PORT:-}" ]]; then
  # Other jobs run Ollama on the default port 11434 on these nodes, so take a free port for this job.
  OLLAMA_PORT="$("${PY}" -c 'import socket; s=socket.socket(); s.bind(("127.0.0.1", 0)); print(s.getsockname()[1]); s.close()')"
fi
OLLAMA_BASE_URL="http://127.0.0.1:${OLLAMA_PORT}/v1"
OLLAMA_HOST_PORT="127.0.0.1:${OLLAMA_PORT}"

# Existence checks. Nothing here reads verifier sources, memory contents, or credentials.
test -s "${AGENT_SIF}" && test -s "${VERIFIER_SIF}" && test -s "${OLLAMA_SIF}" && test -d "${SOURCE_TASK}"
test -s "${INSTRUCTION}" && test -s "${PROMPT_TEMPLATE_SRC}" && test -s "${HARBOR_WRAPPER}"
test -s "${RECORDS_HELPER}" && test -s "${CODEX_HELPER}" && test -s "${NEW_HELPER}"
test -x "${VENV_SOURCE}/bin/python" && test -x "${PYTHON_SOURCE}/bin/python3.12"
test -x "${CODEX_NODE_DIR}/bin/node" && test -e "${CODEX_NPM_DIR}/bin/codex"
test -f "${MODEL_STORE}/manifests/registry.ollama.ai/library/qwen3.8/27b-mtp-q4_K_M"

TEMPLATE_SHA="$(sha256sum "${PROMPT_TEMPLATE_SRC}" | awk '{print $1}')"
if [[ "${TEMPLATE_SHA}" != "${EXPECTED_TEMPLATE_SHA}" ]]; then
  echo "Base prompt template sha256 does not match job-301916; aborting." >&2; exit 5
fi

mkdir -p "${RUN_DIR}/preflight" "${RUN_DIR}/ollama/tmp" "${BUILD_ROOT}" logs
date --iso-8601=seconds >"${RUN_DIR}/started-at.txt"
printf '%s\n' "${TRIAL_ORDER}" >"${RUN_DIR}/trial-order.txt"
printf '%s\n' "${TEMPLATE_SHA}  ${PROMPT_TEMPLATE_SRC}" >"${RUN_DIR}/prompt-template-sha256.txt"
sha256sum "${INSTRUCTION}" >"${RUN_DIR}/instruction-sha256.txt"
sha256sum "${HARBOR_WRAPPER}" "${CODEX_HELPER}" "${RECORDS_HELPER}" "${NEW_HELPER}" "${BASH_SOURCE[0]}" >"${RUN_DIR}/harness-sha256.txt"
printf 'HARBOR_SINGULARITY_EXEC_TIMEOUT_SEC=%s\nTRIAL_TIMEOUT_SEC=%s\nOLLAMA_PORT=%s\n' \
  "${HARBOR_SINGULARITY_EXEC_TIMEOUT_SEC}" "${TRIAL_TIMEOUT_SEC}" "${OLLAMA_PORT}" >"${RUN_DIR}/run-settings.txt"
if [[ -n "${SLURM_JOB_ID:-}" ]]; then scontrol show job "${SLURM_JOB_ID}" >"${RUN_DIR}/slurm-job.txt"; fi
nvidia-smi --query-gpu=name,memory.total,memory.free --format=csv >"${RUN_DIR}/gpu.csv"
nvidia-smi -q >"${RUN_DIR}/nvidia-smi.txt"
"${REPO}/.venv/bin/harbor" --version >"${RUN_DIR}/harbor-version.txt"
apptainer version >"${RUN_DIR}/apptainer-version.txt"

ACTUAL_MEMORY_DIGEST=""
if [[ "${HAS_B}" == 1 ]]; then
  "${PY}" "${NEW_HELPER}" seed-memory --memory-dir "${FROZEN_MEMORY_DIR}" --codex-home "${BUILD_ROOT}" \
    --expected-digest "${EXPECTED_MEMORY_DIGEST}" --output "${RUN_DIR}/preflight/memory-check-only.json" >/dev/null
  rm -rf "${BUILD_ROOT}/memories"
  ACTUAL_MEMORY_DIGEST="$("${PY}" -c 'import json,sys; print(json.load(open(sys.argv[1]))["memory_sha256"])' "${RUN_DIR}/preflight/memory-check-only.json")"
fi

# ------------------------------------------------------------- Ollama server
# One server and one model load for the whole job, as in the Ollama A/B runner.
apptainer exec --fakeroot --nv \
  --bind "${MODEL_STORE}:/models" --bind "${RUN_DIR}/ollama:/ollama-logs" \
  --env OLLAMA_MODELS=/models --env OLLAMA_HOST="${OLLAMA_HOST_PORT}" \
  --env OLLAMA_CONTEXT_LENGTH="${OLLAMA_CONTEXT_LENGTH}" --env OLLAMA_KEEP_ALIVE=20m \
  --env OLLAMA_MAX_LOADED_MODELS=1 --env OLLAMA_NUM_PARALLEL=1 \
  --env OLLAMA_DEBUG_LOG_REQUESTS=true --env TMPDIR=/ollama-logs/tmp \
  "${OLLAMA_SIF}" ollama serve >"${RUN_DIR}/ollama/server.log" 2>&1 &
SERVER_PID=$!
cleanup() {
  if [[ -n "${SERVER_PID:-}" ]]; then kill "${SERVER_PID}" 2>/dev/null || true; wait "${SERVER_PID}" 2>/dev/null || true; fi
  date --iso-8601=seconds >"${RUN_DIR}/finished-at.txt"
  cleanup_codex_home
}
CURRENT_CH=""
cleanup_codex_home() {
  if [[ -n "${CURRENT_CH}" ]]; then rm -rf "${CURRENT_CH}"; CURRENT_CH=""; fi
}
trap cleanup EXIT

READY=0
for attempt in $(seq 1 60); do
  if curl --fail --silent --max-time 5 "http://${OLLAMA_HOST_PORT}/api/version" >"${RUN_DIR}/ollama/api-version.json"; then READY=1; break; fi
  sleep 2
done
test "${READY}" = 1
curl --fail --silent --max-time 30 "http://${OLLAMA_HOST_PORT}/api/tags" >"${RUN_DIR}/ollama/tags.json"
if ! grep -Fq "${MODEL}" "${RUN_DIR}/ollama/tags.json"; then
  echo "Model ${MODEL} is absent from Ollama tags; refusing to download weights inside the job." >&2; exit 3
fi
# Model parameters as stored (temperature is only settable here, not from Codex).
curl --fail --silent --max-time 30 "http://${OLLAMA_HOST_PORT}/api/show" -H 'Content-Type: application/json' \
  -d "{\"name\":\"${MODEL}\"}" >"${RUN_DIR}/ollama/show.json"
"${PY}" -c 'import json,sys; d=json.load(open(sys.argv[1])); print("parameters:", d.get("parameters","")) ' \
  "${RUN_DIR}/ollama/show.json" >"${RUN_DIR}/ollama/show-parameters.txt" || true

# ---------------------------------------------------------- container helpers
write_config() {  # $1 = CODEX_HOME dir, $2 = variant (responses-custom-provider | oss-ollama-builtin)
  local variant="$2"
  {
    echo "model = \"${MODEL}\""
    if [[ "${variant}" == responses-custom-provider ]]; then echo 'model_provider = "local_ollama"'; fi
    cat <<EOF
model_reasoning_effort = "${REASONING}"
model_context_window = ${OLLAMA_CONTEXT_LENGTH}
model_auto_compact_token_limit = 49152
web_search = "disabled"

EOF
    if [[ "${variant}" == responses-custom-provider ]]; then
      cat <<EOF
[model_providers.local_ollama]
name = "Local Ollama (Slurm job)"
base_url = "${OLLAMA_BASE_URL}"
wire_api = "responses"

EOF
    fi
    cat <<'EOF'
[features]
memories = true
plugins = false
remote_plugin = false
plugin_sharing = false
apps = false
browser_use = false
in_app_browser = false
computer_use = false
multi_agent = false
EOF
  } >"$1/config.toml"
  chmod 600 "$1/config.toml"
}

build_codex_cmd() {  # $1 = workspace dir, $2 = CODEX_HOME dir; sets CODEX_APPTAINER
  # --cleanenv: no host environment (no OPENAI_*, no proxies). No --net: host network, so 127.0.0.1 is the job's Ollama.
  CODEX_APPTAINER=(apptainer exec --containall --cleanenv --no-home --pwd /workspace
    --bind "$1:/workspace" --bind "$2:/codex-home"
    --bind "${CODEX_NODE_DIR}:/opt/codex-node:ro" --bind "${CODEX_NPM_DIR}:/opt/codex-npm:ro"
    --env CODEX_HOME=/codex-home --env HOME=/codex-home --env LANG=C.UTF-8
    --env PATH=/opt/codex-node/bin:/opt/codex-npm/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin
    --env CODEX_OSS_BASE_URL="${OLLAMA_BASE_URL}"
    --env NO_PROXY=127.0.0.1,localhost --env no_proxy=127.0.0.1,localhost
    "${AGENT_SIF}")
}

codex_flags() {  # $1 = variant; prints one flag per line, workspace is /workspace
  local variant="$1"
  printf '%s\n' --json --ephemeral --skip-git-repo-check --dangerously-bypass-approvals-and-sandbox \
    --model "${MODEL}" --enable unified_exec -c "model_reasoning_effort=${REASONING}" \
    -c web_search=disabled -C /workspace
  if [[ "${variant}" == oss-ollama-builtin ]]; then printf '%s\n' --oss --local-provider ollama; fi
}

gin_offset() { if [[ -f "$1" ]]; then wc -l <"$1"; else echo 0; fi; }
body_list() { find "${RUN_DIR}/ollama/tmp" -name '*_body.json' -printf '%f\n' 2>/dev/null | sort; }
ps_snapshot() { curl --fail --silent --max-time 10 "http://${OLLAMA_HOST_PORT}/api/ps" >"$1" || echo '{}' >"$1"; }

# ------------------------------------------------ container preflight (no auth, no OpenAI)
PRE_CH="${RUN_DIR}/preflight/codex-home"
mkdir -p "${PRE_CH}" "${RUN_DIR}/preflight/workspace"
chmod 700 "${PRE_CH}"
chmod 777 "${RUN_DIR}/preflight/workspace"
write_config "${PRE_CH}" responses-custom-provider
cat >"${RUN_DIR}/preflight/container-check.sh" <<'EOF'
#!/bin/bash
echo "host_home_visible=$( [ -e /home/csgrad ] && echo yes || echo no )"
echo "workspace_entries_at_start=$(ls -A /workspace | wc -l)"
echo "node_version=$(node --version 2>&1 | tail -1)"
echo "codex_version=$(codex --version 2>/dev/null | grep -m1 -o 'codex-cli.*')"
echo "auth_json_in_codex_home=$( [ -e /codex-home/auth.json ] && echo yes || echo no )"
echo "openai_or_anthropic_env_vars=$(env | grep -c -E '^(OPENAI_|CODEX_API_KEY|ANTHROPIC_)' || true)"
echo "ollama_api_version_from_container=$(curl -s --max-time 20 http://__OLLAMA_HOST_PORT__/api/version)"
echo "memories_feature=$(codex features list 2>/dev/null | awk '$1=="memories" {print $NF}')"
echo "disabled_features_not_false=$(codex features list 2>/dev/null | awk '$1=="plugins"||$1=="apps"||$1=="browser_use"||$1=="multi_agent"||$1=="computer_use"||$1=="remote_plugin"||$1=="plugin_sharing"||$1=="in_app_browser" {if ($NF!="false") print $1}' | tr '\n' ' ')"
EOF
sed -i "s|__OLLAMA_HOST_PORT__|${OLLAMA_HOST_PORT}|" "${RUN_DIR}/preflight/container-check.sh"
PRE_WS="${RUN_DIR}/preflight/workspace"
build_codex_cmd "${PRE_WS}" "${PRE_CH}"
set +e
"${CODEX_APPTAINER[@]}" /bin/bash -s <"${RUN_DIR}/preflight/container-check.sh" >"${RUN_DIR}/preflight/container-preflight.txt" 2>&1
PRE_RC=$?
set -e
PRE_OUT="${RUN_DIR}/preflight/container-preflight.txt"
if [[ "${PRE_RC}" != 0 ]]; then echo "container preflight exited ${PRE_RC}" >&2; exit 6; fi
grep -qx 'host_home_visible=no' "${PRE_OUT}" || { echo "preflight: host /home/csgrad is visible in the container" >&2; exit 6; }
grep -qx 'workspace_entries_at_start=0' "${PRE_OUT}" || { echo "preflight: /workspace is not empty" >&2; exit 6; }
grep -qx 'auth_json_in_codex_home=no' "${PRE_OUT}" || { echo "preflight: an auth.json is present in CODEX_HOME" >&2; exit 6; }
grep -qx 'openai_or_anthropic_env_vars=0' "${PRE_OUT}" || { echo "preflight: a provider credential variable reached the container" >&2; exit 6; }
grep -q "^ollama_api_version_from_container={\"version\"" "${PRE_OUT}" || { echo "preflight: host Ollama not reachable from the container" >&2; exit 6; }
grep -qx 'memories_feature=true' "${PRE_OUT}" || { echo "preflight: memories feature is not on" >&2; exit 6; }
grep -qx 'disabled_features_not_false=' "${PRE_OUT}" || { echo "preflight: a feature that must be off is on" >&2; exit 6; }
rm -rf "${PRE_CH}"

# ------------------------------------------------ provider probe (at most 2 variants)
PROBE_PROMPT="${RUN_DIR}/preflight/probe-prompt.txt"
printf '%s\n' 'Reply with exactly the word READY. Do not run any commands.' >"${PROBE_PROMPT}"
VARIANT=""
for variant in responses-custom-provider oss-ollama-builtin; do
  pdir="${RUN_DIR}/preflight/probe-${variant}"
  mkdir -p "${pdir}/home" "${pdir}/workspace"
  chmod 700 "${pdir}/home"; chmod 777 "${pdir}/workspace"
  write_config "${pdir}/home" "${variant}"
  printf '%s\n' "$(sha256sum "${pdir}/home/config.toml" | awk '{print $1}')" >"${pdir}/config-sha256.txt"
  build_codex_cmd "${pdir}/workspace" "${pdir}/home"
  mapfile -t FLAGS < <(codex_flags "${variant}")
  gin_start="$(gin_offset "${RUN_DIR}/ollama/server.log")"
  set +e
  timeout --signal=INT --kill-after=30s "${PROBE_TIMEOUT_SEC}" "${CODEX_APPTAINER[@]}" codex exec "${FLAGS[@]}" - \
    <"${PROBE_PROMPT}" >"${pdir}/events.jsonl" 2>"${pdir}/codex-stderr.log"
  probe_rc=$?
  set -e
  "${PY}" "${CODEX_HELPER}" summarize-events --events "${pdir}/events.jsonl" --output "${pdir}/events-summary.json"
  "${PY}" "${NEW_HELPER}" probe-check --summary "${pdir}/events-summary.json" --server-log "${RUN_DIR}/ollama/server.log" \
    --gin-offset "${gin_start}" --codex-rc "${probe_rc}" --variant "${variant}" --output "${pdir}/probe.json" && probe_ok=1 || probe_ok=0
  cat "${pdir}/probe.json"
  rm -rf "${pdir}/home"
  if [[ "${probe_ok}" == 1 ]]; then VARIANT="${variant}"; break; fi
  echo "probe variant ${variant} failed; see ${pdir}/codex-stderr.log" >&2
done
if [[ -z "${VARIANT}" ]]; then
  echo "No Codex provider variant reached Ollama with a completed model turn. Stopping before any trial." >&2
  exit 7
fi
printf '%s\n' "${VARIANT}" >"${RUN_DIR}/preflight/provider-variant.txt"
ps_snapshot "${RUN_DIR}/ollama/ps-before-trials.json"
"${PY}" -c 'import json,sys; ms=json.load(open(sys.argv[1])).get("models") or []; ctx=[m.get("context_length") for m in ms if m.get("name")==sys.argv[2]]; print("loaded_context_length", ctx); sys.exit(0 if ctx==[int(sys.argv[3])] else 1)' "${RUN_DIR}/ollama/ps-before-trials.json" "${MODEL}" "${OLLAMA_CONTEXT_LENGTH}" >"${RUN_DIR}/ollama/loaded-context-check.txt" || { echo "Loaded model context is not ${OLLAMA_CONTEXT_LENGTH}; see ollama/ps-before-trials.json" >&2; exit 8; }

# ---------------------------------------------------------------- one trial
run_trial() {
  local index="$1" condition="$2"
  local tag="trial-${index}-${condition}"
  local tdir="${RUN_DIR}/${tag}"
  local ws="${tdir}/workspace"
  local prompt="${tdir}/prompt.txt"
  local gdir="${tdir}/grading"
  local gws="${gdir}/workspace"
  local gtask="${BUILD_ROOT}/${tag}/grade/build-word2vec-pipeline"
  local job_name="frontiermemory-word2vec-codex-ollama-job${JOB_ID}-t${index}-${condition}"
  local grade_job="${job_name}-grade"
  local mounts_json prompt_sha config_sha memory_sha="" codex_rc grade_rc timed_out="false" t0 t1 gin_start
  local mode="none"
  [[ "${condition}" == B ]] && mode="native-memories-folder"

  mkdir -p "${tdir}" "${ws}" "${gdir}"
  if [[ -n "$(ls -A "${ws}")" ]]; then echo "${tag}: workspace is not empty at start" >&2; return 1; fi
  chmod 777 "${ws}"
  printf '%s\n' "${job_name}" >"${tdir}/codex-job-name.txt"
  printf '%s\n' "${grade_job}" >"${tdir}/harbor-grade-job-name.txt"
  date --iso-8601=seconds >"${tdir}/started-at.txt"
  ps_snapshot "${tdir}/ollama-ps-before.json"
  body_list >"${tdir}/ollama-bodies-before.txt"
  gin_start="$(gin_offset "${RUN_DIR}/ollama/server.log")"

  # 1. Prompt: same shared template for A and B (single placeholder substitution).
  "${PY}" "${CODEX_HELPER}" render-prompt --template "${PROMPT_TEMPLATE_SRC}" --instruction "${INSTRUCTION}" --output "${prompt}" >"${tdir}/prompt-sha256.txt"
  prompt_sha="$(awk '{print $1}' "${tdir}/prompt-sha256.txt")"

  # 2. Private CODEX_HOME outside the repo: config only, no auth. B seeds memories/ the way codex.py does.
  CURRENT_CH="$(mktemp -d "${TMPDIR:-/tmp}/codex-ollama-home.XXXXXX")"
  chmod 700 "${CURRENT_CH}"
  write_config "${CURRENT_CH}" "${VARIANT}"
  config_sha="$(sha256sum "${CURRENT_CH}/config.toml" | awk '{print $1}')"
  if [[ "${condition}" == B ]]; then
    "${PY}" "${NEW_HELPER}" seed-memory --memory-dir "${FROZEN_MEMORY_DIR}" --codex-home "${CURRENT_CH}" \
      --expected-digest "${EXPECTED_MEMORY_DIGEST}" --output "${tdir}/memory-seed.json"
    memory_sha="$("${PY}" -c 'import json,sys; print(json.load(open(sys.argv[1]))["memory_sha256"])' "${tdir}/memory-seed.json")"
  fi

  # 3. Codex run inside the task agent container, under the task agent timeout.
  build_codex_cmd "${ws}" "${CURRENT_CH}"
  mapfile -t FLAGS < <(codex_flags "${VARIANT}")
  t0="$(date +%s)"
  set +e
  timeout --signal=INT --kill-after=30s "${TRIAL_TIMEOUT_SEC}" \
    "${CODEX_APPTAINER[@]}" codex exec "${FLAGS[@]}" - \
    <"${prompt}" >"${tdir}/events.jsonl" 2>"${tdir}/codex-stderr.log"
  codex_rc=$?
  set -e
  t1="$(date +%s)"
  if [[ "${codex_rc}" == 124 || "${codex_rc}" == 137 ]]; then timed_out="true"; fi
  date --iso-8601=seconds >"${tdir}/codex-finished-at.txt"
  cp "${CURRENT_CH}/config.toml" "${tdir}/codex-config.toml"
  rm -rf "${CURRENT_CH}"; CURRENT_CH=""
  "${PY}" "${CODEX_HELPER}" summarize-events --events "${tdir}/events.jsonl" --output "${tdir}/events-summary.json"
  "${PY}" "${NEW_HELPER}" run-meta --output "${tdir}/run-meta.json" \
    "codex_exit_code=${codex_rc}" "timed_out=${timed_out}" "agent_wall_sec=$((t1 - t0))" \
    "prompt_sha256=${prompt_sha}" "memory_sha256=${memory_sha}" "config_sha256=${config_sha}" \
    "codex_version=$(grep '^codex_version=' "${RUN_DIR}/preflight/container-preflight.txt" | cut -d= -f2-)" \
    "auth_refreshed=false" "auth_copied_back=false" "condition=${condition}"
  "${PY}" "${NEW_HELPER}" ollama-audit --body-dir "${RUN_DIR}/ollama/tmp" --before-list "${tdir}/ollama-bodies-before.txt" \
    --server-log "${RUN_DIR}/ollama/server.log" --gin-offset "${gin_start}" --model "${MODEL}" --effort "${REASONING}" \
    --output "${tdir}/ollama-audit.json"
  ps_snapshot "${tdir}/ollama-ps-after.json"

  # 4. Grade a copy of the workspace with the unchanged verifier (Harbor nop agent, wrapped path).
  mkdir -p "${gws}"
  chmod 777 "${gws}"
  cp -a "${ws}/." "${gws}/"
  "${PY}" scripts/stage_word2vec_task_for_apptainer.py --source "${SOURCE_TASK}" --output "${gtask}" --agent-image "${AGENT_SIF}" --verifier-image "${VERIFIER_SIF}" >"${gdir}/task-staging.json"
  "${PY}" "${RECORDS_HELPER}" check-task --task-toml "${gtask}/task.toml" --staging "${gdir}/task-staging.json" --output "${gdir}/staged-task-preflight.json"
  mounts_json="$("${PY}" -c 'import json,sys; p,w=sys.argv[1:]; print(json.dumps([{"type":"bind","source":p+"/bin/python3.12","target":"/usr/bin/python3"},{"type":"bind","source":w,"target":"/workspace"}]))' "${PYTHON_SOURCE}" "${gws}")"
  printf '%s\n' "${mounts_json}" >"${gdir}/environment-mounts.json"
  set +e
  APPTAINER_BINDPATH="${HARBOR_SHARED_BINDPATH}" SINGULARITY_BINDPATH="${HARBOR_SHARED_BINDPATH}" \
    timeout --signal=INT --kill-after=60s "${GRADE_GUARD}" "${PY}" "${HARBOR_WRAPPER}" run \
    --path "${gtask}" --env singularity --mounts-json "${mounts_json}" --jobs-dir jobs --job-name "${grade_job}" \
    --agent nop --n-attempts 1 --n-concurrent 1 --agent-timeout-multiplier 1.0 --agent-setup-timeout-multiplier 0.5 --yes \
    >"${gdir}/harbor.log" 2>&1
  grade_rc=$?
  set -e
  printf '%s\n' "${grade_rc}" >"${gdir}/harbor-exit-code.txt"
  if [[ -d "jobs/${grade_job}" ]]; then
    local hsrc
    hsrc="$(find "jobs/${grade_job}" -mindepth 1 -maxdepth 1 -type d -print -quit)"
    if [[ -n "${hsrc}" ]]; then cp -a "${hsrc}" "${gdir}/harbor-trial"; fi
  fi

  # 5. Sanitized record (counts and status only), then provider and Ollama audit fields.
  "${PY}" "${CODEX_HELPER}" trial-record --trial-dir "${tdir}" --grade-dir "${gdir}" --job-dir "jobs/${grade_job}" \
    --job-id "${JOB_ID}" --index "${index}" --condition "${condition}" --model "${MODEL}" --reasoning "${REASONING}" \
    --harbor-exit "${grade_rc}" --agent-timeout-sec "${TRIAL_TIMEOUT_SEC}" --output "${tdir}/trial-record.json"
  "${PY}" "${NEW_HELPER}" augment --trial-record "${tdir}/trial-record.json" --audit "${tdir}/ollama-audit.json" \
    --ps-before "${tdir}/ollama-ps-before.json" --ps-after "${tdir}/ollama-ps-after.json" \
    --provider "$([[ "${VARIANT}" == responses-custom-provider ]] && echo local_ollama-responses || echo ollama-oss-builtin)" \
    --variant "${VARIANT}" --base-url-host "${OLLAMA_HOST_PORT}" --model "${MODEL}" --memory-mode "${mode}"
  date --iso-8601=seconds >"${tdir}/finished-at.txt"
  echo "trial ${index} condition=${condition} codex_exit=${codex_rc} timed_out=${timed_out} grade_exit=${grade_rc}"
}

INDEX=0
for token in "${TRIAL_TOKENS[@]}"; do
  INDEX=$((INDEX + 1))
  run_trial "${INDEX}" "${token}"
done

ps_snapshot "${RUN_DIR}/ollama/ps-after-trials.json"
"${PY}" "${CODEX_HELPER}" aggregate --run-dir "${RUN_DIR}" --job-id "${JOB_ID}" --trial-order "${TRIAL_ORDER}"
date --iso-8601=seconds >"${RUN_DIR}/run-body-finished-at.txt"
