#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
UV_BIN="${UV_BIN:-${REPO_ROOT}/runtime/uv/bin/uv}"
PYTHON_BIN="${PYTHON_BIN:-${REPO_ROOT}/runtime/uv/bin/python3.12}"
VENV_DIR="${OPENHANDS_VENV_DIR:-${REPO_ROOT}/runtime/openhands-sdk-venv}"
LOCK_FILE="${REPO_ROOT}/configs/openhands-sdk-python312-lock.txt"

test -x "${UV_BIN}" || { echo "Missing existing uv runtime: ${UV_BIN}" >&2; exit 2; }
test -x "${PYTHON_BIN}" || { echo "Missing existing Python 3.12 runtime: ${PYTHON_BIN}" >&2; exit 2; }
test -s "${LOCK_FILE}" || { echo "Missing pinned package list: ${LOCK_FILE}" >&2; exit 2; }

"${UV_BIN}" venv "${VENV_DIR}" --python "${PYTHON_BIN}" --clear
"${UV_BIN}" pip install --python "${VENV_DIR}/bin/python" -r "${LOCK_FILE}"
"${VENV_DIR}/bin/python" -c \
  'import openhands.sdk, openhands.tools, fastapi; print("openhands-sdk", openhands.sdk.__version__); print("fastapi", fastapi.__version__)'
