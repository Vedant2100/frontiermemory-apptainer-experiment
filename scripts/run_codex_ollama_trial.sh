#!/usr/bin/env bash
# Generic Codex CLI trial with a LOCAL model: Codex talks to an Ollama server that this Slurm GPU job
# starts itself (qwen3.8:27b-mtp-q4_K_M, num_ctx 65536, reasoning effort medium).
# TASK selects the task: build-word2vec-pipeline (workspace /workspace, 6 cases),
# dapt-intrusion-detection-workflow-learning (working dir /root, artifact /root/network_stats.csv, 37 cases), or
# cattrs-compositional-changelog (patch task: repo /app, declared artifact /logs/artifacts/model.patch from the
# task's [[verifier.collect]] command, 77 cases). For the patch task the runner runs that collect command on the
# agent's repo after Codex finishes, saves model.patch in the trial directory, and grades it through Harbor.
# scripts/run_codex_ollama_word2vec_trial.sh is the earlier word2vec-only runner and is left unchanged.
#
# No OpenAI or ChatGPT credentials are used: no auth.json is copied, the container runs with --containall
# and --cleanenv, and the Codex provider points at 127.0.0.1 only. Apptainer shares the host network (no
# --net), so the task agent container reaches the host Ollama at 127.0.0.1:<OLLAMA_PORT>.
#
# Writable task directory (DAPT): the agent SIF is read-only, so each trial gets a fresh host directory
# filled from the image's own /root (tar stream out of the image, then a sha256 manifest compared with a
# manifest computed inside the image). That directory is bound at /root for Codex, so Codex's changes
# persist on the host. Grading takes the agent's final /root/network_stats.csv and binds that single file
# at /root/network_stats.csv in the Harbor nop agent container, which is where Harbor collects the
# declared artifact (same path as scripts/check-dapt-oracle-collection.sbatch).
#
# Memory is seeded the way frontier_memory.agents.codex.MemoryCodex does it: the whole memory folder is
# copied to $CODEX_HOME/memories/, memory_summary.md is that folder's MEMORY.md when it has no
# memory_summary.md of its own, and features.memories is on for A and B. Codex runs with --ephemeral,
# web search off (-c web_search=disabled), and --enable unified_exec, as Harbor's Codex agent does.
#
# Env:
#   TASK            build-word2vec-pipeline (default) or dapt-intrusion-detection-workflow-learning.
#   TRIAL_ORDER     space-separated arm tokens (default: A). A0 or A = no memory (condition A).
#                   B = legacy single memory arm: FROZEN_MEMORY_DIR + EXPECTED_MEMORY_DIGEST (condition B).
#                   Any other token must be a NAME from MEMORY_ARMS (condition B).
#   MEMORY_ARMS     several memory arms, "NAME=/abs/dir@digest;NAME2=/abs/dir2@digest2". NAME matches
#                   ^[A-Z][A-Z0-9]*$; A, A0 and B are reserved. Every arm's digest is verified at job start
#                   (fail fast), and again per trial. Trial dirs are trial-<i>-<ARM>.
#   FROZEN_MEMORY_DIR      memory folder for legacy arm B (required when TRIAL_ORDER has a B).
#   EXPECTED_MEMORY_DIGEST official folder digest the legacy B memory must match (required with B).
#   --dry-run-arms  (argument) validate MEMORY_ARMS and TRIAL_ORDER, verify digests, print the plan, and exit
#                   before any GPU, Ollama, or Harbor work. Writes nothing under results/.
#   Balanced order (preregistered, 3 rounds of a Latin rotation): see
#     python3 scripts/codex_ollama_trial_helper.py balanced-order --arms A0,R25,M3,G,GR
#   OLLAMA_PORT     port for the job's Ollama server (default: a free port picked at start).
#   PROBE_TIMEOUT_SEC  provider probe timeout (default 600).
#   GRADE_GUARD     outer hang guard for each grading Harbor call (default 2700s, as in the DAPT oracle check).
#   MODEL, REASONING, OLLAMA_CONTEXT_LENGTH  fixed to qwen3.8:27b-mtp-q4_K_M, medium, 65536.
# The agent timeout comes from the staged task.toml ([agent] timeout_sec), not from an env var.
# Records hold counts, names, and status only. Raw event streams, request bodies, and the task
# directories stay under results/ and are not committed.
set -euo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "${REPO}"
export PATH="${REPO}/bin:${PATH}"
export APPTAINER_CACHEDIR="${REPO}/containers/apptainer-cache"
PY="${REPO}/.venv/bin/python"

MODEL="${MODEL:-qwen3.8:27b-mtp-q4_K_M}"
REASONING="${REASONING:-medium}"
OLLAMA_CONTEXT_LENGTH="${OLLAMA_CONTEXT_LENGTH:-65536}"
if [[ "${MODEL}" != "qwen3.8:27b-mtp-q4_K_M" ]]; then echo "Only model qwen3.8:27b-mtp-q4_K_M is allowed here." >&2; exit 2; fi
if [[ "${REASONING}" != "medium" ]]; then echo "REASONING must be medium." >&2; exit 2; fi
if [[ "${OLLAMA_CONTEXT_LENGTH}" != "65536" ]]; then echo "OLLAMA_CONTEXT_LENGTH must be 65536." >&2; exit 2; fi

TASK="${TASK:-build-word2vec-pipeline}"
JOB_ID="${SLURM_JOB_ID:-local-$(date +%Y%m%d%H%M%S)}"
case "${TASK}" in
  build-word2vec-pipeline)
    AGENT_SIF="${REPO}/containers/frontier-memory-word2vec-agent.sif"
    VERIFIER_SIF="${REPO}/containers/frontier-memory-word2vec-verifier-harbor-py310.sif"
    RUN_DIR="${REPO}/results/word2vec-codex-ollama/job-${JOB_ID}"
    ;;
  dapt-intrusion-detection-workflow-learning)
    AGENT_SIF="${REPO}/containers/frontier-memory-dapt-agent.sif"
    VERIFIER_SIF="${REPO}/containers/frontier-memory-dapt-verifier-v2.sif"
    RUN_DIR="${REPO}/results/frontiermemory-dapt/codex-ollama-job-${JOB_ID}"
    ;;
  cattrs-compositional-changelog)
    AGENT_SIF="${REPO}/containers/frontier-memory-cattrs.sif"
    VERIFIER_SIF="${REPO}/containers/frontier-memory-cattrs-verifier.sif"
    RUN_DIR="${REPO}/results/cattrs-codex-ollama/job-${JOB_ID}"
    ;;
  *) echo "TASK must be build-word2vec-pipeline, dapt-intrusion-detection-workflow-learning, or cattrs-compositional-changelog: ${TASK}" >&2; exit 2 ;;
esac
# Working directory inside the agent container: /workspace (word2vec), /root (DAPT), or /app (cattrs repo).
case "${TASK}" in
  build-word2vec-pipeline) WORKDIR_IN=/workspace ;;
  cattrs-compositional-changelog) WORKDIR_IN=/app ;;
  *) WORKDIR_IN=/root ;;
esac
IS_W2V=0
[[ "${TASK}" == build-word2vec-pipeline ]] && IS_W2V=1
# Patch task: the agent edits a repository copy (populated from the image's /app, like DAPT's /root), and the
# declared artifact is the patch that the task's collect command produces from that repository.
IS_PATCH=0
[[ "${TASK}" == cattrs-compositional-changelog ]] && IS_PATCH=1
IS_DAPT=0
[[ "${TASK}" == dapt-intrusion-detection-workflow-learning ]] && IS_DAPT=1
# Image directory that a per-trial working directory is copied from (same as WORKDIR_IN for file tasks).
IMAGE_WORKDIR="${WORKDIR_IN}"

DRY_RUN_ARMS=0
if [[ "${1:-}" == --dry-run-arms ]]; then DRY_RUN_ARMS=1; shift; fi
if [[ $# -gt 0 ]]; then echo "unknown argument: $1" >&2; exit 2; fi

# ------------------------------------------------------------- memory arms and trial order
# Each TRIAL_ORDER token is an arm name. Arm A0 (or the legacy A) has no memory and condition A. Every other arm
# has memory and condition B. Arms come from MEMORY_ARMS, plus the legacy B from FROZEN_MEMORY_DIR.
TRIAL_ORDER="${TRIAL_ORDER:-A}"
MEMORY_ARMS="${MEMORY_ARMS:-}"
FROZEN_MEMORY_DIR="${FROZEN_MEMORY_DIR:-}"
EXPECTED_MEMORY_DIGEST="${EXPECTED_MEMORY_DIGEST:-}"
ARM_HELPER="${REPO}/scripts/codex_ollama_trial_helper.py"
declare -A ARM_DIR=() ARM_DIGEST=()
ARM_NAMES=()        # every memory arm defined for this job, in definition order (legacy B first)
read -r -a TRIAL_TOKENS <<<"${TRIAL_ORDER}"
if [[ "${#TRIAL_TOKENS[@]}" -lt 1 ]]; then echo "TRIAL_ORDER is empty" >&2; exit 2; fi

for token in "${TRIAL_TOKENS[@]}"; do
  if [[ "${token}" == B ]]; then
    # Legacy single memory arm: FROZEN_MEMORY_DIR and EXPECTED_MEMORY_DIGEST, as before.
    if [[ -z "${FROZEN_MEMORY_DIR}" || -z "${EXPECTED_MEMORY_DIGEST}" ]]; then
      echo "TRIAL_ORDER has B: set FROZEN_MEMORY_DIR and EXPECTED_MEMORY_DIGEST." >&2; exit 4
    fi
    test -d "${FROZEN_MEMORY_DIR}"
    if [[ -z "${ARM_DIR[B]:-}" ]]; then
      ARM_NAMES+=(B); ARM_DIR[B]="${FROZEN_MEMORY_DIR}"; ARM_DIGEST[B]="${EXPECTED_MEMORY_DIGEST}"
    fi
  fi
done

if [[ -n "${MEMORY_ARMS}" ]]; then
  IFS=';' read -r -a ARM_SPECS <<<"${MEMORY_ARMS}"
  for spec in "${ARM_SPECS[@]}"; do
    spec="${spec#"${spec%%[![:space:]]*}"}"; spec="${spec%"${spec##*[![:space:]]}"}"
    [[ -z "${spec}" ]] && continue
    if [[ "${spec}" != *=*@* ]]; then echo "MEMORY_ARMS entry must be NAME=/abs/dir@digest (name ${spec%%=*})" >&2; exit 4; fi
    name="${spec%%=*}"; rest="${spec#*=}"; dir="${rest%@*}"; digest="${rest##*@}"
    if [[ ! "${name}" =~ ^[A-Z][A-Z0-9]*$ ]]; then echo "arm name must match ^[A-Z][A-Z0-9]*\$: ${name}" >&2; exit 4; fi
    case "${name}" in A|A0|B) echo "arm name ${name} is reserved" >&2; exit 4 ;; esac
    if [[ -n "${ARM_DIR[${name}]:-}" ]]; then echo "duplicate MEMORY_ARMS name: ${name}" >&2; exit 4; fi
    if [[ "${dir}" != /* ]]; then echo "arm ${name}: folder must be an absolute path" >&2; exit 4; fi
    if [[ ! "${digest}" =~ ^[0-9a-f]{64}$ ]]; then echo "arm ${name}: digest must be 64 lowercase hex characters" >&2; exit 4; fi
    ARM_NAMES+=("${name}"); ARM_DIR[${name}]="${dir}"; ARM_DIGEST[${name}]="${digest}"
  done
fi

for token in "${TRIAL_TOKENS[@]}"; do
  case "${token}" in
    A|A0) ;;
    B) ;;
    *) if [[ -z "${ARM_DIR[${token}]:-}" ]]; then
         echo "TRIAL_ORDER token must be A0, A, B, or a MEMORY_ARMS name: ${token}" >&2; exit 2
       fi ;;
  esac
done

# Fail fast: every defined memory arm must match its digest before any trial or GPU work starts.
ARM_VERIFY_LINES=()
for arm in ${ARM_NAMES[@]+"${ARM_NAMES[@]}"}; do
  line="$("${PY}" "${ARM_HELPER}" verify-memory --name "${arm}" --memory-dir "${ARM_DIR[${arm}]}" \
    --expected-digest "${ARM_DIGEST[${arm}]}")" || { echo "arm ${arm}: memory verification failed; no trial started." >&2; exit 4; }
  ARM_VERIFY_LINES+=("${line}")
done

if [[ "${DRY_RUN_ARMS}" == 1 ]]; then
  echo "dry run (no GPU, Ollama, or Harbor work):"
  for line in ${ARM_VERIFY_LINES[@]+"${ARM_VERIFY_LINES[@]}"}; do echo "  arm ${line}"; done
  index=0
  for token in "${TRIAL_TOKENS[@]}"; do
    index=$((index + 1))
    cond=B; [[ "${token}" == A || "${token}" == A0 ]] && cond=A
    echo "  trial ${index}: arm=${token} condition=${cond} dir=trial-${index}-${token}"
  done
  echo "  total trials: ${#TRIAL_TOKENS[@]}"
  exit 0
fi

PROBE_TIMEOUT_SEC="${PROBE_TIMEOUT_SEC:-600}"
GRADE_GUARD="${GRADE_GUARD:-2700s}"

# Shared word2vec base prompt template (same bytes as the word2vec Codex runner). Used for word2vec only;
# the DAPT prompt gets the same header built from the staged task metadata.
TEMPLATE_DIR="${REPO}/results/word2vec-openhands/ab-v2/job-301916"
PROMPT_TEMPLATE_SRC="${TEMPLATE_DIR}/base-prompt-template.j2"
EXPECTED_TEMPLATE_SHA="$(awk '{print $1}' "${TEMPLATE_DIR}/base-prompt-template-sha256.txt")"
SOURCE_TASK="${REPO}/data/tasks/frontier-memory/${TASK}"
INSTRUCTION="${SOURCE_TASK}/instruction.md"

OLLAMA_SIF="${REPO}/containers/ollama.sif"
MODEL_STORE="/home/csgrad/vbork001/shared-mem-gov-pilot/models"
VENV_SOURCE="${REPO}/runtime/openhands-sdk-venv"
PYTHON_SOURCE="${REPO}/runtime/uv/python/cpython-3.12-linux-x86_64-gnu"
HARBOR_SHARED_BINDPATH="${PYTHON_SOURCE}:${PYTHON_SOURCE},${VENV_SOURCE}:/opt/harbor-server"
HARBOR_WRAPPER="${REPO}/scripts/harbor_singularity_exec_timeout.py"
export HARBOR_SINGULARITY_EXEC_TIMEOUT_SEC="${HARBOR_SINGULARITY_EXEC_TIMEOUT_SEC:-7200}"
CODEX_HELPER="${REPO}/scripts/word2vec_codex_trial.py"
NEW_HELPER="${REPO}/scripts/word2vec_codex_ollama_helper.py"
TASK_HELPER="${REPO}/scripts/codex_ollama_trial_helper.py"

CODEX_RUNTIME="${CODEX_RUNTIME:-/home/csgrad/vbork001/codex-runtime}"
CODEX_NODE_DIR="$(readlink -f "${CODEX_RUNTIME}/node/current")"
CODEX_NPM_DIR="$(readlink -f "${CODEX_RUNTIME}/npm-global")"

BUILD_ROOT="${REPO}/build/${TASK}/codex-ollama/job-${JOB_ID}"
META_DIR="${BUILD_ROOT}/meta"

if [[ -z "${OLLAMA_PORT:-}" ]]; then
  OLLAMA_PORT="$("${PY}" -c 'import socket; s=socket.socket(); s.bind(("127.0.0.1", 0)); print(s.getsockname()[1]); s.close()')"
fi
OLLAMA_BASE_URL="http://127.0.0.1:${OLLAMA_PORT}/v1"
OLLAMA_HOST_PORT="127.0.0.1:${OLLAMA_PORT}"

# Existence checks. Nothing here reads verifier sources, memory contents, or credentials.
test -s "${AGENT_SIF}" && test -s "${VERIFIER_SIF}" && test -s "${OLLAMA_SIF}" && test -d "${SOURCE_TASK}"
test -s "${INSTRUCTION}" && test -s "${HARBOR_WRAPPER}"
test -s "${CODEX_HELPER}" && test -s "${NEW_HELPER}" && test -s "${TASK_HELPER}"
test -x "${VENV_SOURCE}/bin/python" && test -x "${PYTHON_SOURCE}/bin/python3.12"
test -x "${CODEX_NODE_DIR}/bin/node" && test -e "${CODEX_NPM_DIR}/bin/codex"
MODEL_STORE_MANIFEST="${MODEL_STORE}/manifests/registry.ollama.ai/library/qwen3.8/27b-mtp-q4_K_M"
test -f "${MODEL_STORE_MANIFEST}"
if [[ "${IS_W2V}" == 1 ]]; then
  test -s "${PROMPT_TEMPLATE_SRC}"
  TEMPLATE_SHA="$(sha256sum "${PROMPT_TEMPLATE_SRC}" | awk '{print $1}')"
  if [[ "${TEMPLATE_SHA}" != "${EXPECTED_TEMPLATE_SHA}" ]]; then
    echo "Base prompt template sha256 does not match job-301916; aborting." >&2; exit 5
  fi
fi

mkdir -p "${RUN_DIR}/preflight" "${RUN_DIR}/ollama/tmp" "${META_DIR}" "${BUILD_ROOT}" logs
date --iso-8601=seconds >"${RUN_DIR}/started-at.txt"
printf '%s\n' "${TASK}" >"${RUN_DIR}/task.txt"
printf '%s\n' "${TRIAL_ORDER}" >"${RUN_DIR}/trial-order.txt"
if [[ ${#ARM_VERIFY_LINES[@]} -gt 0 ]]; then printf '%s\n' "${ARM_VERIFY_LINES[@]}" >"${RUN_DIR}/memory-arms.jsonl"; fi
sha256sum "${INSTRUCTION}" >"${RUN_DIR}/instruction-sha256.txt"
sha256sum "${HARBOR_WRAPPER}" "${CODEX_HELPER}" "${NEW_HELPER}" "${TASK_HELPER}" "${BASH_SOURCE[0]}" >"${RUN_DIR}/harness-sha256.txt"
if [[ "${IS_W2V}" == 1 ]]; then printf '%s\n' "${TEMPLATE_SHA}  ${PROMPT_TEMPLATE_SRC}" >"${RUN_DIR}/prompt-template-sha256.txt"; fi

# Task metadata from the staged copy (the staged task.toml carries the Apptainer images and the public
# verifier network mode). Staging only rewrites docker_image and the verifier network mode.
"${PY}" scripts/stage_word2vec_task_for_apptainer.py --source "${SOURCE_TASK}" --output "${META_DIR}/${TASK}" \
  --agent-image "${AGENT_SIF}" --verifier-image "${VERIFIER_SIF}" >"${RUN_DIR}/preflight/task-staging.json"
"${PY}" "${TASK_HELPER}" task-meta --task "${TASK}" --task-toml "${META_DIR}/${TASK}/task.toml" \
  --output "${RUN_DIR}/preflight/task-meta.json"
TRIAL_TIMEOUT_SEC="$("${PY}" -c 'import json,sys; print(int(float(json.load(open(sys.argv[1]))["agent_timeout_sec"])))' "${RUN_DIR}/preflight/task-meta.json")"
ARTIFACT_REL="$("${PY}" -c 'import json,sys; print(json.load(open(sys.argv[1]))["artifact_rel"][0])' "${RUN_DIR}/preflight/task-meta.json")"
CASES_TOTAL="$("${PY}" -c 'import json,sys; print(json.load(open(sys.argv[1]))["cases_total"])' "${RUN_DIR}/preflight/task-meta.json")"
# Patch tasks only: the task's own [[verifier.collect]] command and its timeout (empty for file tasks).
COLLECT_COMMAND="$("${PY}" -c 'import json,sys; print(json.load(open(sys.argv[1])).get("collect_command", ""))' "${RUN_DIR}/preflight/task-meta.json")"
COLLECT_TIMEOUT_SEC="$("${PY}" -c 'import json,sys; print(json.load(open(sys.argv[1])).get("collect_timeout_sec", 300))' "${RUN_DIR}/preflight/task-meta.json")"
if [[ "${IS_PATCH}" == 1 && -z "${COLLECT_COMMAND}" ]]; then echo "patch task without a collect command" >&2; exit 2; fi
printf 'TASK=%s\nHARBOR_SINGULARITY_EXEC_TIMEOUT_SEC=%s\nTRIAL_TIMEOUT_SEC=%s\nPROBE_TIMEOUT_SEC=%s\nGRADE_GUARD=%s\nOLLAMA_PORT=%s\nWORKDIR_IN=%s\nARTIFACT_REL=%s\nCASES_TOTAL=%s\n' \
  "${TASK}" "${HARBOR_SINGULARITY_EXEC_TIMEOUT_SEC}" "${TRIAL_TIMEOUT_SEC}" "${PROBE_TIMEOUT_SEC}" "${GRADE_GUARD}" \
  "${OLLAMA_PORT}" "${WORKDIR_IN}" "${ARTIFACT_REL}" "${CASES_TOTAL}" >"${RUN_DIR}/run-settings.txt"
if [[ -n "${SLURM_JOB_ID:-}" ]]; then scontrol show job "${SLURM_JOB_ID}" >"${RUN_DIR}/slurm-job.txt"; fi
nvidia-smi --query-gpu=name,memory.total,memory.free --format=csv >"${RUN_DIR}/gpu.csv"
nvidia-smi -q >"${RUN_DIR}/nvidia-smi.txt"
"${REPO}/.venv/bin/harbor" --version >"${RUN_DIR}/harbor-version.txt"
apptainer version >"${RUN_DIR}/apptainer-version.txt"

# ------------------------------------------------- DAPT: image /root and verifier checks (hash level)
if [[ "${IS_DAPT}" == 1 ]]; then
  # Official task file hashes and verifier-image test hashes (hashing only, as in the DAPT oracle check).
  (cd "${SOURCE_TASK}" && find . -type f -print0 | sort -z | xargs -0 sha256sum) >"${RUN_DIR}/official-task-sha256.txt"
  sha256sum "${SOURCE_TASK}/tests/test.sh" "${SOURCE_TASK}/tests/test_outputs.py" >"${RUN_DIR}/verifier-source-sha256.txt"
  sha256sum "${VERIFIER_SIF}" >"${RUN_DIR}/verifier-image-sha256.txt"
  apptainer exec --fakeroot --pwd /tests "${VERIFIER_SIF}" sha256sum /tests/test.sh /tests/test_outputs.py >"${RUN_DIR}/verifier-image-tests-sha256.txt"
  "${PY}" - "${RUN_DIR}/verifier-source-sha256.txt" "${RUN_DIR}/verifier-image-tests-sha256.txt" <<'PY'
import pathlib, sys
source, image = (pathlib.Path(path) for path in sys.argv[1:])
source_hashes = [line.split()[0] for line in source.read_text().splitlines()]
image_hashes = [line.split()[0] for line in image.read_text().splitlines()]
if source_hashes != image_hashes or len(source_hashes) != 2:
    raise SystemExit("Verifier SIF test files differ from the pinned task source")
PY
  apptainer exec --fakeroot --pwd /tests "${VERIFIER_SIF}" /bin/bash -lc 'test -s /tests/test.sh && test -s /tests/test_outputs.py && /usr/bin/python3 -c "import sys,pytest,scapy,pandas,numpy; print(\"verifier-python\",sys.version.split()[0],\"pytest\",pytest.__version__)"' >"${RUN_DIR}/preflight/verifier-image-preflight.txt" 2>&1
  # Agent image: the input files and the Python packages the task uses. Its /root is the template for every trial.
  apptainer exec --containall --cleanenv --no-home --pwd /root "${AGENT_SIF}" /bin/bash -c \
    'find . -type f -print0 | sort -z | xargs -0 sha256sum' >"${RUN_DIR}/preflight/image-root-sha256.txt"
  grep -q ' ./packets.pcap$' "${RUN_DIR}/preflight/image-root-sha256.txt"
  grep -q ' ./network_stats.csv$' "${RUN_DIR}/preflight/image-root-sha256.txt"
  apptainer exec --containall --cleanenv --no-home --pwd /root "${AGENT_SIF}" /bin/bash -c \
    'python3 -c "import scapy,pandas,numpy,sys; print(\"agent-python\",sys.version.split()[0])"' >"${RUN_DIR}/preflight/agent-python.txt" 2>&1
fi

# ------------------------------------------- patch task: verifier test hashes, image repo at base commit
if [[ "${IS_PATCH}" == 1 ]]; then
  (cd "${SOURCE_TASK}/tests" && find . -type f -print0 | sort -z | xargs -0 sha256sum) >"${RUN_DIR}/verifier-source-tests-sha256.txt"
  apptainer exec --fakeroot --pwd /tests "${VERIFIER_SIF}" /bin/bash -c \
    'cd /tests && find . -type f -print0 | sort -z | xargs -0 sha256sum' >"${RUN_DIR}/verifier-image-tests-sha256.txt"
  if ! diff <(sort "${RUN_DIR}/verifier-source-tests-sha256.txt") <(sort "${RUN_DIR}/verifier-image-tests-sha256.txt") >/dev/null; then
    echo "Verifier SIF test files differ from the pinned task source" >&2; exit 5
  fi
  BASE_COMMIT="$("${PY}" -c 'import sys,tomllib; print(tomllib.load(open(sys.argv[1],"rb"))["metadata"]["base_commit_hash"])' "${SOURCE_TASK}/task.toml")"
  apptainer exec --containall --cleanenv --no-home --pwd "${IMAGE_WORKDIR}" "${AGENT_SIF}" /bin/bash -c \
    'git -C /app rev-parse HEAD; git -C /app status --porcelain | wc -l' >"${RUN_DIR}/preflight/image-repo-head.txt"
  grep -qx "${BASE_COMMIT}" "${RUN_DIR}/preflight/image-repo-head.txt" || { echo "image /app HEAD is not the base commit" >&2; exit 5; }
  # Agent image manifest of the repository (the template for every trial's populated /app).
  apptainer exec --containall --cleanenv --no-home --pwd "${IMAGE_WORKDIR}" "${AGENT_SIF}" /bin/bash -c \
    'find . -type f -print0 | sort -z | xargs -0 sha256sum' >"${RUN_DIR}/preflight/image-root-sha256.txt"
fi

# Fill a per-trial working directory from the image's /root and check it against the image manifest.
populate_workdir() {  # $1 = host directory to become WORKDIR_IN inside the agent container
  local dest="$1"
  mkdir -p "${dest}"
  chmod 755 "${dest}"
  if [[ "${IS_W2V}" == 1 ]]; then
    chmod 777 "${dest}"
    return 0
  fi
  apptainer exec --containall --cleanenv --no-home --pwd "${IMAGE_WORKDIR}" "${AGENT_SIF}" tar -C "${IMAGE_WORKDIR}" -cf - . 2>>"${dest}.populate.log" \
    | tar -C "${dest}" -xf - 2>>"${dest}.populate.log"
  "${PY}" "${TASK_HELPER}" manifest --root "${dest}" --output "${dest}.manifest-sha256.txt"
  if ! diff <(sort "${RUN_DIR}/preflight/image-root-sha256.txt") <(sort "${dest}.manifest-sha256.txt") >"${dest}.manifest.diff"; then
    echo "populated ${dest} does not match the image /root manifest; see ${dest}.manifest.diff" >&2; return 1
  fi
}

# ------------------------------------------------------------ Ollama server
# One server and one model load for the whole job, as in the word2vec runner.
apptainer exec --fakeroot --nv \
  --bind "${MODEL_STORE}:/models" --bind "${RUN_DIR}/ollama:/ollama-logs" \
  --env OLLAMA_MODELS=/models --env OLLAMA_HOST="${OLLAMA_HOST_PORT}" \
  --env OLLAMA_CONTEXT_LENGTH="${OLLAMA_CONTEXT_LENGTH}" --env OLLAMA_KEEP_ALIVE=20m \
  --env OLLAMA_MAX_LOADED_MODELS=1 --env OLLAMA_NUM_PARALLEL=1 \
  --env OLLAMA_DEBUG_LOG_REQUESTS=true --env TMPDIR=/ollama-logs/tmp \
  "${OLLAMA_SIF}" ollama serve >"${RUN_DIR}/ollama/server.log" 2>&1 &
SERVER_PID=$!
CURRENT_CH=""
cleanup_codex_home() {
  if [[ -n "${CURRENT_CH}" ]]; then rm -rf "${CURRENT_CH}"; CURRENT_CH=""; fi
}
cleanup() {
  if [[ -n "${SERVER_PID:-}" ]]; then kill "${SERVER_PID}" 2>/dev/null || true; wait "${SERVER_PID}" 2>/dev/null || true; fi
  date --iso-8601=seconds >"${RUN_DIR}/finished-at.txt"
  cleanup_codex_home
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

build_codex_cmd() {  # $1 = host working directory (bound at WORKDIR_IN), $2 = CODEX_HOME dir; sets CODEX_APPTAINER
  # --containall --cleanenv: no host environment and no host home. No --net: host network, so 127.0.0.1 is the job's Ollama.
  CODEX_APPTAINER=(apptainer exec --containall --cleanenv --no-home --pwd "${WORKDIR_IN}"
    --bind "$1:${WORKDIR_IN}" --bind "$2:/codex-home"
    --bind "${CODEX_NODE_DIR}:/opt/codex-node:ro" --bind "${CODEX_NPM_DIR}:/opt/codex-npm:ro"
    --env CODEX_HOME=/codex-home --env HOME=/codex-home --env LANG=C.UTF-8
    --env PATH=/opt/codex-node/bin:/opt/codex-npm/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin
    --env CODEX_OSS_BASE_URL="${OLLAMA_BASE_URL}"
    --env NO_PROXY=127.0.0.1,localhost --env no_proxy=127.0.0.1,localhost
    "${AGENT_SIF}")
}

codex_flags() {  # $1 = variant; prints one flag per line, working directory is WORKDIR_IN
  local variant="$1"
  printf '%s\n' --json --ephemeral --skip-git-repo-check --dangerously-bypass-approvals-and-sandbox \
    --model "${MODEL}" --enable unified_exec -c "model_reasoning_effort=${REASONING}" \
    -c web_search=disabled -C "${WORKDIR_IN}"
  if [[ "${variant}" == oss-ollama-builtin ]]; then printf '%s\n' --oss --local-provider ollama; fi
}

gin_offset() { if [[ -f "$1" ]]; then wc -l <"$1"; else echo 0; fi; }
body_list() { find "${RUN_DIR}/ollama/tmp" -name '*_body.json' -printf '%f\n' 2>/dev/null | sort; }
ps_snapshot() { curl --fail --silent --max-time 10 "http://${OLLAMA_HOST_PORT}/api/ps" >"$1" || echo '{}' >"$1"; }

# ----------------------------------------------- container preflight (no auth, no OpenAI)
PRE_CH="${RUN_DIR}/preflight/codex-home"
PRE_WS="${RUN_DIR}/preflight/workdir"
mkdir -p "${PRE_CH}"
chmod 700 "${PRE_CH}"
populate_workdir "${PRE_WS}"
write_config "${PRE_CH}" responses-custom-provider
cat >"${RUN_DIR}/preflight/container-check.sh" <<'EOF'
#!/bin/bash
echo "host_home_visible=$( [ -e /home/csgrad ] && echo yes || echo no )"
echo "workdir_entries_at_start=$(ls -A __WORKDIR__ | wc -l)"
echo "workdir_packets_pcap=$( [ -s __WORKDIR__/packets.pcap ] && echo yes || echo no )"
echo "node_version=$(node --version 2>&1 | tail -1)"
echo "codex_version=$(codex --version 2>/dev/null | grep -m1 -o 'codex-cli.*')"
echo "auth_json_in_codex_home=$( [ -e /codex-home/auth.json ] && echo yes || echo no )"
echo "openai_or_anthropic_env_vars=$(env | grep -c -E '^(OPENAI_|CODEX_API_KEY|ANTHROPIC_)' || true)"
echo "ollama_api_version_from_container=$(curl -s --max-time 20 http://__OLLAMA_HOST_PORT__/api/version)"
echo "memories_feature=$(codex features list 2>/dev/null | awk '$1=="memories" {print $NF}')"
echo "disabled_features_not_false=$(codex features list 2>/dev/null | awk '$1=="plugins"||$1=="apps"||$1=="browser_use"||$1=="multi_agent"||$1=="computer_use"||$1=="remote_plugin"||$1=="plugin_sharing"||$1=="in_app_browser" {if ($NF!="false") print $1}' | tr '\n' ' ')"
EOF
if [[ "${IS_PATCH}" == 1 ]]; then
  cat >>"${RUN_DIR}/preflight/container-check.sh" <<'EOF'
echo "workdir_git=$( [ -d __WORKDIR__/.git ] && echo yes || echo no )"
EOF
fi
sed -i -e "s|__OLLAMA_HOST_PORT__|${OLLAMA_HOST_PORT}|" -e "s|__WORKDIR__|${WORKDIR_IN}|g" "${RUN_DIR}/preflight/container-check.sh"
build_codex_cmd "${PRE_WS}" "${PRE_CH}"
set +e
"${CODEX_APPTAINER[@]}" /bin/bash -s <"${RUN_DIR}/preflight/container-check.sh" >"${RUN_DIR}/preflight/container-preflight.txt" 2>&1
PRE_RC=$?
set -e
PRE_OUT="${RUN_DIR}/preflight/container-preflight.txt"
if [[ "${PRE_RC}" != 0 ]]; then echo "container preflight exited ${PRE_RC}" >&2; exit 6; fi
grep -qx 'host_home_visible=no' "${PRE_OUT}" || { echo "preflight: host /home/csgrad is visible in the container" >&2; exit 6; }
if [[ "${IS_W2V}" == 1 ]]; then
  grep -qx 'workdir_entries_at_start=0' "${PRE_OUT}" || { echo "preflight: /workspace is not empty" >&2; exit 6; }
elif [[ "${IS_PATCH}" == 1 ]]; then
  grep -qx 'workdir_git=yes' "${PRE_OUT}" || { echo "preflight: no repository (.git) in ${WORKDIR_IN}" >&2; exit 6; }
else
  grep -qx 'workdir_packets_pcap=yes' "${PRE_OUT}" || { echo "preflight: /root/packets.pcap is missing in the container" >&2; exit 6; }
fi
grep -qx 'auth_json_in_codex_home=no' "${PRE_OUT}" || { echo "preflight: an auth.json is present in CODEX_HOME" >&2; exit 6; }
grep -qx 'openai_or_anthropic_env_vars=0' "${PRE_OUT}" || { echo "preflight: a provider credential variable reached the container" >&2; exit 6; }
grep -q "^ollama_api_version_from_container={\"version\"" "${PRE_OUT}" || { echo "preflight: host Ollama not reachable from the container" >&2; exit 6; }
grep -qx 'memories_feature=true' "${PRE_OUT}" || { echo "preflight: memories feature is not on" >&2; exit 6; }
grep -qx 'disabled_features_not_false=' "${PRE_OUT}" || { echo "preflight: a feature that must be off is on" >&2; exit 6; }
rm -rf "${PRE_CH}" "${PRE_WS}"

# ------------------------------------------------ provider probe (at most 2 variants)
PROBE_PROMPT="${RUN_DIR}/preflight/probe-prompt.txt"
printf '%s\n' 'Reply with exactly the word READY. Do not run any commands.' >"${PROBE_PROMPT}"
VARIANT=""
for variant in responses-custom-provider oss-ollama-builtin; do
  pdir="${RUN_DIR}/preflight/probe-${variant}"
  mkdir -p "${pdir}/home"
  chmod 700 "${pdir}/home"
  populate_workdir "${pdir}/workdir"
  write_config "${pdir}/home" "${variant}"
  printf '%s\n' "$(sha256sum "${pdir}/home/config.toml" | awk '{print $1}')" >"${pdir}/config-sha256.txt"
  build_codex_cmd "${pdir}/workdir" "${pdir}/home"
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
  rm -rf "${pdir}/home" "${pdir}/workdir"
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

# Patch tasks: run the task's own [[verifier.collect]] command on the agent's repository after Codex has finished,
# as Harbor does after the agent phase. The repository is bound at WORKDIR_IN; /logs is a host directory so the
# command's /logs/artifacts/model.patch lands there. Saves ${2}/model.patch (copied, not modified) and the exit code.
run_patch_collect() {  # $1 = agent workspace (bound at WORKDIR_IN), $2 = trial directory
  local tdir="$2" cdir="$2/collect" rc
  rm -rf "${cdir}"
  mkdir -p "${cdir}/logs" "${cdir}/home"
  chmod 700 "${cdir}/home"
  set +e
  timeout --signal=INT --kill-after=30s "${COLLECT_TIMEOUT_SEC}" apptainer exec --containall --cleanenv \
    --writable-tmpfs --home "${cdir}/home:/collect-home" \
    --pwd "${WORKDIR_IN}" --bind "$1:${WORKDIR_IN}" --bind "${cdir}/logs:/logs" \
    "${AGENT_SIF}" /bin/bash -c "${COLLECT_COMMAND}" >"${tdir}/collect-stdout.txt" 2>"${tdir}/collect-stderr.txt"
  rc=$?
  set -e
  printf '%s\n' "${rc}" >"${tdir}/collect-exit.txt"
  if [[ -f "${cdir}/logs/artifacts/model.patch" ]]; then cp -p "${cdir}/logs/artifacts/model.patch" "${tdir}/model.patch"; fi
  rm -rf "${cdir}"
}

# ---------------------------------------------------------------- one trial
run_trial() {
  local index="$1" arm="$2" condition
  case "${arm}" in A|A0) condition=A ;; *) condition=B ;; esac
  local tag="trial-${index}-${arm}"
  local tdir="${RUN_DIR}/${tag}"
  local ws="${tdir}/${WORKDIR_IN#/}"          # host directory bound at WORKDIR_IN (workspace or root)
  local prompt="${tdir}/prompt.txt"
  local gdir="${tdir}/grading"
  local gws="${gdir}/workspace"
  local gtask="${BUILD_ROOT}/${tag}/grade/${TASK}"
  local job_name="frontiermemory-codex-ollama-${TASK:0:24}-job${JOB_ID}-t${index}-${arm}"
  local grade_job="${job_name}-grade"
  local mounts_json prompt_sha config_sha memory_sha="" codex_rc grade_rc timed_out="false" t0 t1 gin_start
  local mode="none" start_sha="" artifact_final="${ws}/${ARTIFACT_REL}"
  # Patch task: the graded artifact is the patch saved by run_patch_collect in the trial directory.
  [[ "${IS_PATCH}" == 1 ]] && artifact_final="${tdir}/model.patch"
  [[ "${condition}" == B ]] && mode="native-memories-folder"

  mkdir -p "${tdir}" "${gdir}"
  printf '%s\n' "${job_name}" >"${tdir}/codex-job-name.txt"
  printf '%s\n' "${grade_job}" >"${tdir}/harbor-grade-job-name.txt"
  date --iso-8601=seconds >"${tdir}/started-at.txt"

  # 0. Working directory: empty (word2vec) or a fresh copy of the image /root (DAPT), with its start hash list.
  populate_workdir "${ws}"
  if [[ "${IS_W2V}" == 0 ]]; then
    mv "${ws}.manifest-sha256.txt" "${tdir}/starting-files-sha256.txt"
    mv "${ws}.manifest.diff" "${tdir}/starting-vs-image.diff"
    mv "${ws}.populate.log" "${tdir}/populate.log"
    start_sha="$(awk -v p="./${ARTIFACT_REL}" '$2==p {print $1}' "${tdir}/starting-files-sha256.txt")"
  elif [[ -n "$(ls -A "${ws}")" ]]; then
    echo "${tag}: workspace is not empty at start" >&2; return 1
  fi
  ps_snapshot "${tdir}/ollama-ps-before.json"
  body_list >"${tdir}/ollama-bodies-before.txt"
  gin_start="$(gin_offset "${RUN_DIR}/ollama/server.log")"

  # 1. Prompt. word2vec: shared template. DAPT: the same header, built from the staged artifact metadata.
  if [[ "${IS_W2V}" == 1 ]]; then
    "${PY}" "${CODEX_HELPER}" render-prompt --template "${PROMPT_TEMPLATE_SRC}" --instruction "${INSTRUCTION}" --output "${prompt}" >"${tdir}/prompt-sha256.txt"
  else
    "${PY}" "${TASK_HELPER}" render-prompt --task-meta "${RUN_DIR}/preflight/task-meta.json" --instruction "${INSTRUCTION}" --output "${prompt}" >"${tdir}/prompt-sha256.txt"
  fi
  prompt_sha="$(awk '{print $1}' "${tdir}/prompt-sha256.txt")"

  # 2. Private CODEX_HOME outside the repo: config only, no auth. B seeds memories/ the way codex.py does.
  CURRENT_CH="$(mktemp -d "${TMPDIR:-/tmp}/codex-ollama-home.XXXXXX")"
  chmod 700 "${CURRENT_CH}"
  write_config "${CURRENT_CH}" "${VARIANT}"
  config_sha="$(sha256sum "${CURRENT_CH}/config.toml" | awk '{print $1}')"
  if [[ "${condition}" == B ]]; then
    "${PY}" "${NEW_HELPER}" seed-memory --memory-dir "${ARM_DIR[${arm}]}" --codex-home "${CURRENT_CH}" \
      --expected-digest "${ARM_DIGEST[${arm}]}" --output "${tdir}/memory-seed.json"
    memory_sha="$("${PY}" -c 'import json,sys; print(json.load(open(sys.argv[1]))["memory_sha256"])' "${tdir}/memory-seed.json")"
  fi

  # 3. Codex run inside the task agent container, under the task agent timeout (task.toml [agent] timeout_sec).
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
  if [[ "${IS_W2V}" == 0 ]]; then
    "${PY}" "${TASK_HELPER}" manifest --root "${ws}" --output "${tdir}/final-files-sha256.txt"
  fi
  if [[ "${IS_PATCH}" == 1 ]]; then
    run_patch_collect "${ws}" "${tdir}"
  fi

  # 4. Grade with the unchanged verifier through Harbor's nop agent (wrapped path, as in the oracle check).
  mkdir -p "${gdir}"
  if [[ "${IS_W2V}" == 1 ]]; then
    mkdir -p "${gws}"
    chmod 777 "${gws}"
    cp -a "${ws}/." "${gws}/"
    mounts_json="$("${PY}" -c 'import json,sys; p,w=sys.argv[1:]; print(json.dumps([{"type":"bind","source":p+"/bin/python3.12","target":"/usr/bin/python3"},{"type":"bind","source":w,"target":"/workspace"}]))' "${PYTHON_SOURCE}" "${gws}")"
  elif [[ "${IS_PATCH}" == 1 ]]; then
    # Patch task: the nop container gets a copy of the agent's repository at WORKDIR_IN. Harbor then runs the task's
    # own collect hook there, which rebuilds the same model.patch for the unchanged verifier. A bind of the saved
    # patch at the declared path would be overwritten by that hook, so the repository is bound instead.
    mkdir -p "${gws}"
    chmod 755 "${gws}"
    cp -a "${ws}/." "${gws}/"
    mounts_json="$("${PY}" -c 'import json,sys; s,t=sys.argv[1:]; print(json.dumps([{"type":"bind","source":s,"target":t}]))' "${gws}" "${WORKDIR_IN}")"
  else
    # Only the declared artifact is handed to grading: a single-file bind at its declared path in the nop container.
    if [[ -s "${artifact_final}" ]]; then
      cp -p "${artifact_final}" "${gdir}/$(basename "${ARTIFACT_REL}")"
      mounts_json="$("${PY}" -c 'import json,sys; s,t=sys.argv[1:]; print(json.dumps([{"type":"bind","source":s,"target":t}]))' \
        "${gdir}/$(basename "${ARTIFACT_REL}")" "${WORKDIR_IN}/${ARTIFACT_REL}")"
    else
      mounts_json='[]'
    fi
  fi
  printf '%s\n' "${mounts_json}" >"${gdir}/environment-mounts.json"
  "${PY}" scripts/stage_word2vec_task_for_apptainer.py --source "${SOURCE_TASK}" --output "${gtask}" \
    --agent-image "${AGENT_SIF}" --verifier-image "${VERIFIER_SIF}" >"${gdir}/task-staging.json"
  cp "${RUN_DIR}/preflight/task-meta.json" "${gdir}/staged-task-preflight.json"
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

  # 5. Sanitized record (counts and status only), then the provider and Ollama audit fields.
  "${PY}" "${TASK_HELPER}" trial-record --task "${TASK}" --trial-dir "${tdir}" --grade-dir "${gdir}" \
    --job-dir "jobs/${grade_job}" --job-id "${JOB_ID}" --index "${index}" --condition "${condition}" --arm "${arm}" \
    --model "${MODEL}" --reasoning "${REASONING}" --harbor-exit "${grade_rc}" --agent-timeout-sec "${TRIAL_TIMEOUT_SEC}" \
    --artifact-file "${artifact_final}" --artifact-start-sha "${start_sha}" \
    --provider-variant "${VARIANT}" --base-url-host "${OLLAMA_HOST_PORT}" --memory-mode "${mode}" \
    --audit "${tdir}/ollama-audit.json" --ps-before "${tdir}/ollama-ps-before.json" --ps-after "${tdir}/ollama-ps-after.json" \
    --output "${tdir}/trial-record.json"
  date --iso-8601=seconds >"${tdir}/finished-at.txt"
  echo "trial ${index} arm=${arm} condition=${condition} codex_exit=${codex_rc} timed_out=${timed_out} grade_exit=${grade_rc}"
}

INDEX=0
for token in "${TRIAL_TOKENS[@]}"; do
  INDEX=$((INDEX + 1))
  run_trial "${INDEX}" "${token}"
done

ps_snapshot "${RUN_DIR}/ollama/ps-after-trials.json"
"${PY}" "${TASK_HELPER}" aggregate --run-dir "${RUN_DIR}" --job-id "${JOB_ID}" --trial-order "${TRIAL_ORDER}"
date --iso-8601=seconds >"${RUN_DIR}/run-body-finished-at.txt"
