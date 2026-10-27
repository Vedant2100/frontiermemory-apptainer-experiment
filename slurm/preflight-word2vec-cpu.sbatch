#!/usr/bin/env bash
#SBATCH --job-name=fm-word2vec-cpu-preflight
#SBATCH --partition=batch
#SBATCH --cpus-per-task=4
#SBATCH --mem=20G
#SBATCH --time=00:30:00
#SBATCH --output=logs/word2vec-cpu-preflight-%j.out
#SBATCH --error=logs/word2vec-cpu-preflight-%j.err

set -euo pipefail
cd /home/csgrad/vbork001/frontiermemory-experiment-20261024

export PATH="${PWD}/bin:${PATH}"
export APPTAINER_CACHEDIR="${PWD}/containers/apptainer-cache"

TASK="${PWD}/data/tasks/frontier-memory/build-word2vec-pipeline"
VERIFIER_SIF="${PWD}/containers/frontier-memory-word2vec-verifier.sif"
AGENT_SIF="${PWD}/containers/frontier-memory-word2vec-agent.sif"
RUN_DIR="${PWD}/results/word2vec-cpu-preflight/job-${SLURM_JOB_ID}"

mkdir -p "${RUN_DIR}/reference-workspace" logs
chmod 777 "${RUN_DIR}/reference-workspace"
date --iso-8601=seconds >"${RUN_DIR}/started-at.txt"
apptainer version >"${RUN_DIR}/apptainer-version.txt"
sha256sum "${TASK}/task.toml" "${TASK}/tests/Dockerfile" \
  "${TASK}/tests/test.sh" "${TASK}/tests/test_outputs.py" \
  >"${RUN_DIR}/official-task-verifier-sha256.txt"

apptainer build --fakeroot --force "${VERIFIER_SIF}" \
  containers/frontier-memory-word2vec-verifier.def \
  >"${RUN_DIR}/build-verifier.log" 2>&1
apptainer build --fakeroot --force "${AGENT_SIF}" \
  containers/frontier-memory-word2vec-agent.def \
  >"${RUN_DIR}/build-agent.log" 2>&1

apptainer exec --fakeroot "${VERIFIER_SIF}" python - <<'PY' \
  >"${RUN_DIR}/verifier-dependencies.txt" 2>&1
import gensim, nltk, numpy, pytest, scipy
print("gensim", gensim.__version__)
print("nltk", nltk.__version__)
print("numpy", numpy.__version__)
print("pytest", pytest.__version__)
print("scipy", scipy.__version__)
PY

WORKSPACE="${RUN_DIR}/reference-workspace"
apptainer exec --fakeroot \
  --bind "${WORKSPACE}:/workspace" \
  --bind "${TASK}/solution:/solution:ro" \
  --bind "${TASK}/tests:/tests:ro" \
  --pwd /workspace "${AGENT_SIF}" \
  /bin/bash /solution/solve.sh \
  >"${RUN_DIR}/reference-solution.log" 2>&1
test -s "${WORKSPACE}/solution.py"

set +e
apptainer exec --fakeroot \
  --bind "${WORKSPACE}:/workspace" \
  --bind "${TASK}/tests:/tests:ro" \
  --pwd /tests "${VERIFIER_SIF}" \
  /bin/bash /tests/test.sh \
  >"${RUN_DIR}/reference-verifier.log" 2>&1
VERIFIER_EXIT=$?
set -e
printf '%s\n' "${VERIFIER_EXIT}" >"${RUN_DIR}/reference-verifier-exit-code.txt"
sha256sum "${TASK}/task.toml" "${TASK}/tests/Dockerfile" \
  "${TASK}/tests/test.sh" "${TASK}/tests/test_outputs.py" \
  >"${RUN_DIR}/official-task-verifier-sha256-after.txt"
date --iso-8601=seconds >"${RUN_DIR}/finished-at.txt"

if [[ "${VERIFIER_EXIT}" -ne 0 ]]; then
  exit "${VERIFIER_EXIT}"
fi
printf 'REFERENCE_VERIFIER_PASS\n' >"${RUN_DIR}/reference-verifier-status.txt"
