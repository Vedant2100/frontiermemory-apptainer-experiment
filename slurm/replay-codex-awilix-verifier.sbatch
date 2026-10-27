#!/usr/bin/env bash
#SBATCH --job-name=fm-codex-awilix-verifier
#SBATCH --partition=batch
#SBATCH --cpus-per-task=4
#SBATCH --mem=16G
#SBATCH --time=00:45:00
#SBATCH --output=logs/codex-awilix-verifier-%j.out
#SBATCH --error=logs/codex-awilix-verifier-%j.err

set -euo pipefail
cd /home/csgrad/vbork001/frontiermemory-experiment-20261024

BASE_COMMIT=82ac179c1de4c216c4e333093044fac643303f0c
SOURCE_REPO="${PWD}/build/codex-awilix-release-tier-implicit"
PATCH_FILE="${PWD}/results/codex-awilix-frontier-2026-10-26/model.patch"
RUN_DIR="${PWD}/results/codex-awilix-frontier-2026-10-26/official-verifier"
CHECKOUT="${PWD}/build/codex-awilix-verifier-${SLURM_JOB_ID}"
ENVIRONMENT_SIF="${PWD}/containers/awilix-release-tier-implicit-serverdeps.sif"
VERIFIER_SIF="${PWD}/containers/awilix-release-tier-implicit-verifier.sif"
NODE_MODULES="${PWD}/build/awilix-existing-node_modules/node_modules"

mkdir -p "${RUN_DIR}/artifacts" "${RUN_DIR}/verifier"
chmod a+rwx "${RUN_DIR}" "${RUN_DIR}/artifacts" "${RUN_DIR}/verifier"
date --iso-8601=seconds > "${RUN_DIR}/started-at.txt"
sha256sum "${PATCH_FILE}" > "${RUN_DIR}/model-patch.sha256"
printf '%s\n' "${BASE_COMMIT}" > "${RUN_DIR}/base-commit.txt"
printf '%s\n' "unchanged test.sh and original-test.sh from the existing verifier SIF; preinstalled node_modules extracted from the existing task SIF and bind-mounted at /app/node_modules because the verifier SIF omits them" > "${RUN_DIR}/replay-mode.txt"

rm -rf "${CHECKOUT}"
cp -a "${SOURCE_REPO}" "${CHECKOUT}"
git -C "${CHECKOUT}" reset --hard "${BASE_COMMIT}"
git -C "${CHECKOUT}" clean -fdx
if [[ ! -x "${NODE_MODULES}/.bin/tsc" ]]; then
  mkdir -p "$(dirname "${NODE_MODULES}")"
  apptainer exec --fakeroot \
    --bind "$(dirname "${NODE_MODULES}"):/extract" \
    "${ENVIRONMENT_SIF}" \
    /bin/bash -lc 'test -x /app/node_modules/.bin/tsc && cp -a /app/node_modules /extract/node_modules'
fi
mkdir -p "${CHECKOUT}/node_modules"
chmod -R a+rwX "${CHECKOUT}"
chmod -R a+rX "${NODE_MODULES}"
install -m 0644 "${PATCH_FILE}" "${RUN_DIR}/artifacts/model.patch"

apptainer exec --fakeroot \
  --bind "${CHECKOUT}:/app" \
  --bind "${NODE_MODULES}:/app/node_modules" \
  --bind "${RUN_DIR}:/logs" \
  "${VERIFIER_SIF}" \
  /bin/bash /tests/test.sh 2>&1 | tee "${RUN_DIR}/verifier-stdout.log"

date --iso-8601=seconds > "${RUN_DIR}/finished-at.txt"
if [[ -f "${RUN_DIR}/verifier/reward.txt" ]]; then
  cp "${RUN_DIR}/verifier/reward.txt" "${RUN_DIR}/strict-reward.txt"
fi
if [[ -f "${RUN_DIR}/verifier/functional-reward.txt" ]]; then
  cp "${RUN_DIR}/verifier/functional-reward.txt" "${RUN_DIR}/functional-reward.txt"
fi
