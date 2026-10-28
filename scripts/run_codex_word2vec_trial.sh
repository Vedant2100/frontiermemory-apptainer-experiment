#!/usr/bin/env bash
# Codex CLI trial for the Word2Vec task (model gpt-reserve, reasoning medium).
#
# Companion harness, outside the Ollama/OpenHands protocol gates in protocol-v2.md.
# Per trial: a fresh empty workspace and a fresh private CODEX_HOME (copy of auth.json plus a
# minimal config.toml; condition B also gets the frozen memory as AGENTS.md). Codex runs inside
# the task agent container with the workspace bound at /workspace, so it cannot see the repo.
# The unchanged verifier then grades a copy of that workspace through Harbor's nop agent, using
# the same wrapped path as slurm/check-word2vec-oracle-collection-wrapped.sbatch.
#
# Env: TRIAL_ORDER (or CONDITION) of A/B tokens, run sequentially. Default A.
#      MODEL must be gpt-reserve and REASONING must be medium.
# Never prints or copies auth.json contents. Records hold counts and status only.
set -euo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "${REPO}"
export PATH="${REPO}/bin:${PATH}"
export APPTAINER_CACHEDIR="${REPO}/containers/apptainer-cache"
PY="${REPO}/.venv/bin/python"

MODEL="${MODEL:-gpt-reserve}"
REASONING="${REASONING:-medium}"
if [[ "${MODEL}" != "gpt-reserve" ]]; then echo "Only model gpt-reserve is allowed here." >&2; exit 2; fi
if [[ "${REASONING}" != "medium" ]]; then echo "REASONING must be medium." >&2; exit 2; fi

if [[ -z "${TRIAL_ORDER:-}" && -n "${CONDITION:-}" ]]; then TRIAL_ORDER="${CONDITION}"; fi
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

JOB_ID="${JOB_ID:-${SLURM_JOB_ID:-local-$(date +%Y%m%d%H%M%S)}}"
TRIAL_TIMEOUT_SEC="${TRIAL_TIMEOUT_SEC:-1200}"   # task.toml [agent] timeout_sec (official stop rule)
GRADE_GUARD="${GRADE_GUARD:-1800s}"              # outer hang guard for the grading Harbor call only

FROZEN_MEMORY="${FROZEN_MEMORY:-${REPO}/memory/frozen-v2/MEMORY.md}"
EXPECTED_MEMORY_SHA256="${EXPECTED_MEMORY_SHA256:-eb044c32ec3246f474cb0dbfa57f3cdbe8d5ddb93f691648eb65ed95b6a578ab}"

# Shared base prompt template from the OpenHands A/B job (identical for A and B).
TEMPLATE_DIR="${REPO}/results/word2vec-openhands/ab-v2/job-301916"
PROMPT_TEMPLATE_SRC="${PROMPT_TEMPLATE_SRC:-${TEMPLATE_DIR}/base-prompt-template.j2}"
EXPECTED_TEMPLATE_SHA="$(awk '{print $1}' "${TEMPLATE_DIR}/base-prompt-template-sha256.txt")"
INSTRUCTION="${INSTRUCTION:-${REPO}/data/tasks/frontier-memory/build-word2vec-pipeline/instruction.md}"

SOURCE_TASK="${REPO}/data/tasks/frontier-memory/build-word2vec-pipeline"
AGENT_SIF="${REPO}/containers/frontier-memory-word2vec-agent.sif"
VERIFIER_SIF="${REPO}/containers/frontier-memory-word2vec-verifier-harbor-py310.sif"
VERIFIER_DEF="${REPO}/containers/frontier-memory-word2vec-verifier-harbor.def"
VENV_SOURCE="${REPO}/runtime/openhands-sdk-venv"
PYTHON_SOURCE="${REPO}/runtime/uv/python/cpython-3.12-linux-x86_64-gnu"
HARBOR_SHARED_BINDPATH="${PYTHON_SOURCE}:${PYTHON_SOURCE},${VENV_SOURCE}:/opt/harbor-server"
HARBOR_WRAPPER="${REPO}/scripts/harbor_singularity_exec_timeout.py"
export HARBOR_SINGULARITY_EXEC_TIMEOUT_SEC="${HARBOR_SINGULARITY_EXEC_TIMEOUT_SEC:-7200}"
RECORDS_HELPER="${REPO}/scripts/word2vec_ab_v2_records.py"
CODEX_HELPER="${REPO}/scripts/word2vec_codex_trial.py"

# Codex CLI install (npm-global package plus Node). The node "current" link is absolute, so the
# real Node directory is bound read-only into the container instead of the symlink.
CODEX_RUNTIME="${CODEX_RUNTIME:-/home/csgrad/vbork001/codex-runtime}"
CODEX_SRC_HOME="${CODEX_SRC_HOME:-${HOME}/.codex}"
CODEX_NODE_DIR="$(readlink -f "${CODEX_RUNTIME}/node/current")"
CODEX_NPM_DIR="$(readlink -f "${CODEX_RUNTIME}/npm-global")"

RUN_DIR="${REPO}/results/word2vec-openhands/codex-v2/job-${JOB_ID}"
BUILD_ROOT="${REPO}/build/word2vec-apptainer/codex-v2/job-${JOB_ID}"

PROXY_ARGS=()
for var in HTTPS_PROXY HTTP_PROXY NO_PROXY https_proxy http_proxy no_proxy; do
  if [[ -n "${!var:-}" ]]; then PROXY_ARGS+=(--env "${var}=${!var}"); fi
done

# Existence checks only. auth.json contents are never read or printed.
test -s "${AGENT_SIF}" && test -s "${VERIFIER_SIF}" && test -s "${VERIFIER_DEF}" && test -d "${SOURCE_TASK}"
test -s "${INSTRUCTION}" && test -s "${PROMPT_TEMPLATE_SRC}" && test -s "${HARBOR_WRAPPER}"
test -s "${RECORDS_HELPER}" && test -s "${CODEX_HELPER}"
test -x "${VENV_SOURCE}/bin/python" && test -x "${PYTHON_SOURCE}/bin/python3.12"
test -x "${CODEX_NODE_DIR}/bin/node" && test -e "${CODEX_NPM_DIR}/bin/codex"
test -s "${CODEX_SRC_HOME}/auth.json"

TEMPLATE_SHA="$(sha256sum "${PROMPT_TEMPLATE_SRC}" | awk '{print $1}')"
if [[ "${TEMPLATE_SHA}" != "${EXPECTED_TEMPLATE_SHA}" ]]; then
  echo "Base prompt template sha256 does not match job-301916; aborting." >&2
  exit 5
fi
if [[ "${HAS_B}" == 1 ]]; then
  test -s "${FROZEN_MEMORY}"
  ACTUAL_MEMORY_SHA="$(sha256sum "${FROZEN_MEMORY}" | awk '{print $1}')"
  if [[ "${ACTUAL_MEMORY_SHA}" != "${EXPECTED_MEMORY_SHA256}" ]]; then
    echo "Frozen memory sha256 mismatch; aborting before any trial." >&2
    exit 4
  fi
fi

mkdir -p "${RUN_DIR}/preflight" "${BUILD_ROOT}" logs
date --iso-8601=seconds >"${RUN_DIR}/started-at.txt"
printf '%s\n' "${TRIAL_ORDER}" >"${RUN_DIR}/trial-order.txt"
printf '%s\n' "${TEMPLATE_SHA}  ${PROMPT_TEMPLATE_SRC}" >"${RUN_DIR}/prompt-template-sha256.txt"
sha256sum "${INSTRUCTION}" >"${RUN_DIR}/instruction-sha256.txt"
sha256sum "${HARBOR_WRAPPER}" "${CODEX_HELPER}" "${RECORDS_HELPER}" "${BASH_SOURCE[0]}" >"${RUN_DIR}/harness-sha256.txt"
printf 'HARBOR_SINGULARITY_EXEC_TIMEOUT_SEC=%s\n' "${HARBOR_SINGULARITY_EXEC_TIMEOUT_SEC}" >"${RUN_DIR}/harbor-exec-timeout.txt"
printf 'TRIAL_TIMEOUT_SEC=%s\n' "${TRIAL_TIMEOUT_SEC}" >"${RUN_DIR}/trial-timeout-sec.txt"
if [[ -n "${SLURM_JOB_ID:-}" ]]; then scontrol show job "${SLURM_JOB_ID}" >"${RUN_DIR}/slurm-job.txt"; fi
"${REPO}/.venv/bin/harbor" --version >"${RUN_DIR}/harbor-version.txt"
apptainer version >"${RUN_DIR}/apptainer-version.txt"

# ------------------------------------------------------------ helpers
write_config() {
  # Minimal config: no MCP servers, no plugins or apps, no native memories. Web search is NOT disabled
  # here: web_search_mode is reported as an ignored setting by codex-cli 0.157 (see the smoke summary).
  cat >"$1/config.toml" <<'EOF'
model = "gpt-reserve"
model_reasoning_effort = "medium"

[features]
memories = false
plugins = false
remote_plugin = false
plugin_sharing = false
apps = false
browser_use = false
in_app_browser = false
computer_use = false
multi_agent = false
EOF
  chmod 600 "$1/config.toml"
}

build_codex_cmd() {  # $1 = workspace dir, $2 = CODEX_HOME dir; sets CODEX_APPTAINER
  CODEX_APPTAINER=(apptainer exec --containall --cleanenv --no-home --pwd /workspace
    --bind "$1:/workspace" --bind "$2:/codex-home"
    --bind "${CODEX_NODE_DIR}:/opt/codex-node:ro" --bind "${CODEX_NPM_DIR}:/opt/codex-npm:ro"
    --env CODEX_HOME=/codex-home --env HOME=/codex-home --env LANG=C.UTF-8
    --env PATH=/opt/codex-node/bin:/opt/codex-npm/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin
    ${PROXY_ARGS[@]+"${PROXY_ARGS[@]}"}
    "${AGENT_SIF}")
}

write_run_meta() {  # $1 = output path, then key=value pairs (digits -> int, true/false -> bool)
  local out="$1"; shift
  "${PY}" -c 'import json,sys
out = {}
for item in sys.argv[2:]:
    key, value = item.split("=", 1)
    if value.isdigit():
        value = int(value)
    elif value in ("true", "false"):
        value = value == "true"
    out[key] = value
open(sys.argv[1], "w", encoding="utf-8").write(json.dumps(out, indent=2) + "\n")' "${out}" "$@"
}

CURRENT_CH=""
CURRENT_AUTH_SHA=""
AUTH_REFRESHED="no"
AUTH_COPIED_BACK="no"
cleanup_codex_home() {
  # Copy a refreshed token back over the source auth.json (mode 600), only if the source is unchanged
  # since our copy was made. Then remove the private CODEX_HOME. Contents are never printed.
  if [[ -n "${CURRENT_CH}" ]]; then
    if [[ -n "${CURRENT_AUTH_SHA}" && -f "${CURRENT_CH}/auth.json" ]]; then
      local now_sha src_sha
      now_sha="$(sha256sum "${CURRENT_CH}/auth.json" | awk '{print $1}')"
      if [[ "${now_sha}" != "${CURRENT_AUTH_SHA}" ]]; then
        AUTH_REFRESHED="yes"
        src_sha="$(sha256sum "${CODEX_SRC_HOME}/auth.json" | awk '{print $1}')"
        if [[ "${src_sha}" == "${CURRENT_AUTH_SHA}" ]]; then
          cat "${CURRENT_CH}/auth.json" >"${CODEX_SRC_HOME}/auth.json"
          chmod 600 "${CODEX_SRC_HOME}/auth.json"
          AUTH_COPIED_BACK="yes"
        fi
      fi
    fi
    rm -rf "${CURRENT_CH}"
    CURRENT_CH=""
    CURRENT_AUTH_SHA=""
  fi
}
trap cleanup_codex_home EXIT

# ------------------------------------------------- container preflight
PRE_CH="$(mktemp -d "${TMPDIR:-/tmp}/codex-preflight.XXXXXX")"
chmod 700 "${PRE_CH}"
write_config "${PRE_CH}"
PRE_WS="${RUN_DIR}/preflight/workspace"
mkdir -p "${PRE_WS}"
chmod 777 "${PRE_WS}"
cat >"${RUN_DIR}/preflight/container-check.sh" <<'EOF'
#!/bin/bash
echo "host_home_visible=$( [ -e /home/csgrad ] && echo yes || echo no )"
echo "home_listing=$(ls -A /home 2>/dev/null | tr '\n' ' ')"
echo "workspace_entries_at_start=$(ls -A /workspace | wc -l)"
echo "node_version=$(node --version 2>&1 | tail -1)"
echo "codex_version=$(codex --version 2>/dev/null | grep -m1 -o 'codex-cli.*')"
echo "disabled_features_not_false=$(codex features list 2>/dev/null | awk '$1=="memories"||$1=="plugins"||$1=="apps"||$1=="browser_use"||$1=="multi_agent"||$1=="computer_use"||$1=="remote_plugin"||$1=="plugin_sharing"||$1=="in_app_browser" {if ($NF!="false") print $1}' | tr '\n' ' ')"
echo "api_openai_http_code=$(curl -s -o /dev/null -w '%{http_code}' --max-time 30 https://api.openai.com/v1/models || true)"
EOF
build_codex_cmd "${PRE_WS}" "${PRE_CH}"
set +e
"${CODEX_APPTAINER[@]}" /bin/bash -s <"${RUN_DIR}/preflight/container-check.sh" >"${RUN_DIR}/preflight/container-preflight.txt" 2>&1
PRE_RC=$?
set -e
rm -rf "${PRE_CH}"
PRE_OUT="${RUN_DIR}/preflight/container-preflight.txt"
if [[ "${PRE_RC}" != 0 ]]; then echo "container preflight exited ${PRE_RC}" >&2; exit 6; fi
grep -qx 'host_home_visible=no' "${PRE_OUT}" || { echo "preflight: host /home/csgrad is visible in the container" >&2; exit 6; }
grep -qx 'workspace_entries_at_start=0' "${PRE_OUT}" || { echo "preflight: /workspace is not empty" >&2; exit 6; }
grep -qx 'disabled_features_not_false=' "${PRE_OUT}" || { echo "preflight: a feature that must be disabled reads back enabled" >&2; exit 6; }
API_CODE="$(grep '^api_openai_http_code=' "${PRE_OUT}" | cut -d= -f2)"
if [[ -z "${API_CODE}" || "${API_CODE}" == 000 ]]; then echo "preflight: api.openai.com not reachable from container" >&2; exit 6; fi
CODEX_VERSION="$(grep '^codex_version=' "${PRE_OUT}" | cut -d= -f2-)"
if [[ -z "${CODEX_VERSION}" ]]; then echo "preflight: codex --version failed inside container" >&2; exit 6; fi
printf '%s\n' "${CODEX_VERSION}" >"${RUN_DIR}/preflight/codex-version.txt"

# ------------------------------------- verifier preflight (as in the oracle check)
sha256sum "${SOURCE_TASK}/tests/test.sh" "${SOURCE_TASK}/tests/test_outputs.py" >"${RUN_DIR}/preflight/verifier-source-sha256.txt"
test -s "${VERIFIER_SIF}"
apptainer exec --fakeroot --pwd /tests "${VERIFIER_SIF}" /bin/bash -lc 'test -s /tests/test.sh && test -s /tests/test_outputs.py && /usr/bin/python3 -c "import sys,gensim,nltk,numpy,pytest,scipy; assert sys.version_info[:2] == (3,10), sys.version; print(\"verifier-python\",sys.version.split()[0])"' >"${RUN_DIR}/preflight/verifier-image-preflight.txt" 2>&1
apptainer exec --fakeroot --pwd /tests "${VERIFIER_SIF}" sha256sum /tests/test.sh /tests/test_outputs.py >"${RUN_DIR}/preflight/verifier-image-tests-sha256.txt"
"${PY}" - "${RUN_DIR}/preflight/verifier-source-sha256.txt" "${RUN_DIR}/preflight/verifier-image-tests-sha256.txt" <<'PY'
import pathlib, sys
source, image = (pathlib.Path(path) for path in sys.argv[1:])
source_hashes = [line.split()[0] for line in source.read_text().splitlines()]
image_hashes = [line.split()[0] for line in image.read_text().splitlines()]
if source_hashes != image_hashes or len(source_hashes) != 2:
    raise SystemExit("Verifier SIF test files differ from the pinned task source")
PY
APPTAINER_BINDPATH="${HARBOR_SHARED_BINDPATH}" SINGULARITY_BINDPATH="${HARBOR_SHARED_BINDPATH}" apptainer exec --no-mount home,tmp,bind-paths --pwd /tests --writable-tmpfs --fakeroot --containall --pid "${VERIFIER_SIF}" /bin/bash -c '/usr/bin/python3 -c "import sys,gensim,nltk,numpy,pytest,scipy; assert sys.version_info[:2] == (3,10), sys.version; print(\"verifier-python\",sys.version.split()[0])" && /opt/harbor-server/bin/python3 -c "import fastapi,uvicorn; print(\"harbor-server-runtime\",fastapi.__version__,uvicorn.__version__)"' >"${RUN_DIR}/preflight/verifier-runtime-preflight.txt" 2>&1
sha256sum "${VERIFIER_SIF}" >"${RUN_DIR}/preflight/verifier-image-sha256.txt"

# ------------------------------------------------------------ one trial
run_trial() {
  local index="$1" condition="$2"
  local tag="trial-${index}-${condition}"
  local tdir="${RUN_DIR}/${tag}"
  local ws="${tdir}/workspace"
  local prompt="${tdir}/prompt.txt"
  local gdir="${tdir}/grading"
  local gws="${gdir}/workspace"
  local job_name="frontiermemory-word2vec-codex-job${JOB_ID}-t${index}-${condition}"
  local grade_job="${job_name}-grade"
  local gtask="${BUILD_ROOT}/${tag}/grade/build-word2vec-pipeline"
  local mounts_json prompt_sha memory_sha="" config_sha codex_rc grade_rc timed_out="false" t0 t1

  mkdir -p "${tdir}" "${ws}" "${gdir}"
  if [[ -n "$(ls -A "${ws}")" ]]; then echo "${tag}: workspace is not empty at start" >&2; return 1; fi
  chmod 777 "${ws}"
  printf '%s\n' "${job_name}" >"${tdir}/codex-job-name.txt"
  printf '%s\n' "${grade_job}" >"${tdir}/harbor-grade-job-name.txt"
  date --iso-8601=seconds >"${tdir}/started-at.txt"

  # 1. Prompt: same shared template for A and B (single placeholder substitution).
  "${PY}" "${CODEX_HELPER}" render-prompt --template "${PROMPT_TEMPLATE_SRC}" --instruction "${INSTRUCTION}" --output "${prompt}" >"${tdir}/prompt-sha256.txt"
  prompt_sha="$(awk '{print $1}' "${tdir}/prompt-sha256.txt")"

  # 2. Private CODEX_HOME outside the repo: auth copy (600) plus config; B adds the frozen memory as AGENTS.md.
  CURRENT_CH="$(mktemp -d "${TMPDIR:-/tmp}/codex-home.XXXXXX")"
  chmod 700 "${CURRENT_CH}"
  cp "${CODEX_SRC_HOME}/auth.json" "${CURRENT_CH}/auth.json"
  chmod 600 "${CURRENT_CH}/auth.json"
  CURRENT_AUTH_SHA="$(sha256sum "${CURRENT_CH}/auth.json" | awk '{print $1}')"
  write_config "${CURRENT_CH}"
  config_sha="$(sha256sum "${CURRENT_CH}/config.toml" | awk '{print $1}')"
  if [[ "${condition}" == B ]]; then
    cp "${FROZEN_MEMORY}" "${CURRENT_CH}/AGENTS.md"
    chmod 600 "${CURRENT_CH}/AGENTS.md"
    memory_sha="$(sha256sum "${CURRENT_CH}/AGENTS.md" | awk '{print $1}')"
  fi

  # 3. Codex run inside the task agent container, under the task agent timeout.
  build_codex_cmd "${ws}" "${CURRENT_CH}"
  t0="$(date +%s)"
  set +e
  timeout --signal=INT --kill-after=30s "${TRIAL_TIMEOUT_SEC}" \
    "${CODEX_APPTAINER[@]}" codex exec --json --ephemeral --skip-git-repo-check \
      --dangerously-bypass-approvals-and-sandbox \
      --model "${MODEL}" -c "model_reasoning_effort=${REASONING}" -C /workspace - \
    <"${prompt}" >"${tdir}/events.jsonl" 2>"${tdir}/codex-stderr.log"
  codex_rc=$?
  set -e
  t1="$(date +%s)"
  if [[ "${codex_rc}" == 124 || "${codex_rc}" == 137 ]]; then timed_out="true"; fi
  date --iso-8601=seconds >"${tdir}/codex-finished-at.txt"
  cleanup_codex_home
  "${PY}" "${CODEX_HELPER}" summarize-events --events "${tdir}/events.jsonl" --output "${tdir}/events-summary.json"
  write_run_meta "${tdir}/run-meta.json" \
    "codex_exit_code=${codex_rc}" "timed_out=${timed_out}" "agent_wall_sec=$((t1 - t0))" \
    "prompt_sha256=${prompt_sha}" "memory_sha256=${memory_sha}" "config_sha256=${config_sha}" \
    "codex_version=${CODEX_VERSION}" "auth_refreshed=${AUTH_REFRESHED}" "auth_copied_back=${AUTH_COPIED_BACK}" \
    "condition=${condition}"
  AUTH_REFRESHED="no"
  AUTH_COPIED_BACK="no"

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

  # 5. Sanitized record (counts and status only).
  "${PY}" "${CODEX_HELPER}" trial-record --trial-dir "${tdir}" --grade-dir "${gdir}" --job-dir "jobs/${grade_job}" \
    --job-id "${JOB_ID}" --index "${index}" --condition "${condition}" --model "${MODEL}" --reasoning "${REASONING}" \
    --harbor-exit "${grade_rc}" --agent-timeout-sec "${TRIAL_TIMEOUT_SEC}" --output "${tdir}/trial-record.json"
  date --iso-8601=seconds >"${tdir}/finished-at.txt"
  echo "trial ${index} condition=${condition} codex_exit=${codex_rc} timed_out=${timed_out} grade_exit=${grade_rc}"
}

INDEX=0
for token in "${TRIAL_TOKENS[@]}"; do
  INDEX=$((INDEX + 1))
  run_trial "${INDEX}" "${token}"
done

"${PY}" "${CODEX_HELPER}" aggregate --run-dir "${RUN_DIR}" --job-id "${JOB_ID}" --trial-order "${TRIAL_ORDER}"
date --iso-8601=seconds >"${RUN_DIR}/finished-at.txt"
