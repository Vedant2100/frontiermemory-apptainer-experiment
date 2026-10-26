#!/usr/bin/env bash
set -euo pipefail

if [[ $# != 1 ]]; then
  echo "Usage: $0 PATH_TO_HARBOR_TASK_COPY" >&2
  exit 2
fi

TASK_PATH="$(realpath "$1")"
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
NODE_BIN="${NODE_BIN:-/home/csgrad/vbork001/codex-runtime/node/current/bin}"
NPM_BIN="${NPM_BIN:-${NODE_BIN}/npm}"
RUNTIME_DIR="${TASK_PATH}/environment/files/pi-runtime"
SHIM_DIR="${TASK_PATH}/environment/files/shims"
PI_PACKAGE_JSON="${RUNTIME_DIR}/lib/node_modules/@earendil-works/pi-coding-agent/package.json"

test -f "${TASK_PATH}/task.toml" || {
  echo "Not a staged Harbor task copy: ${TASK_PATH}" >&2
  exit 2
}
test -x "${NODE_BIN}/node" || {
  echo "Node 22 runtime not found at ${NODE_BIN}; set NODE_BIN to the existing Node runtime" >&2
  exit 2
}
test -x "${NPM_BIN}" || {
  echo "npm not found at ${NPM_BIN}; set NPM_BIN to the npm executable for Node 22" >&2
  exit 2
}

mkdir -p "${RUNTIME_DIR}" "${SHIM_DIR}"
if [[ ! -f "${PI_PACKAGE_JSON}" ]] \
  || ! grep -q '"version": "0.85.1"' "${PI_PACKAGE_JSON}"; then
  "${NPM_BIN}" install --prefix "${RUNTIME_DIR}" --global --ignore-scripts \
    @earendil-works/pi-coding-agent@0.85.1
fi
cp "${REPO_ROOT}/scripts/pi-offline-shims/curl" "${SHIM_DIR}/curl"
cp "${REPO_ROOT}/scripts/pi-offline-shims/npm" "${SHIM_DIR}/npm"
chmod 755 "${SHIM_DIR}/curl" "${SHIM_DIR}/npm"

PI_BIN="${RUNTIME_DIR}/bin/pi"
test -x "${PI_BIN}"
export PATH="${NODE_BIN}:${PATH}"
"${PI_BIN}" --version | grep -Fx '0.85.1'
