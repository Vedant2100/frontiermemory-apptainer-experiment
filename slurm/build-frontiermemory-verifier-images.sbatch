#!/usr/bin/env bash
#SBATCH --job-name=fm-verifier-images
#SBATCH --partition=batch
#SBATCH --cpus-per-task=4
#SBATCH --mem=16G
#SBATCH --time=00:45:00
#SBATCH --output=logs/frontiermemory-verifier-build-%j.out
#SBATCH --error=logs/frontiermemory-verifier-build-%j.err

set -euo pipefail
cd /home/csgrad/vbork001/frontiermemory-experiment-20261024
export APPTAINER_CACHEDIR="${PWD}/containers/apptainer-cache"
mkdir -p "${APPTAINER_CACHEDIR}"

build_and_check() {
  local sif="$1"
  local definition="$2"
  apptainer build --fakeroot --force "${sif}" "${definition}"
  apptainer exec --fakeroot "${sif}" sh -lc \
    'test -f /tests/test.sh && test -x /tests/test.sh && test -d /logs/verifier && getent passwd agent && getent group agent'
  sha256sum "${sif}"
}

BUILD_SCOPE="${BUILD_SCOPE:-both}"
case "${BUILD_SCOPE}" in
  both)
    build_and_check containers/frontier-memory-cattrs-verifier.sif \
      containers/frontier-memory-cattrs-verifier.def
    build_and_check containers/frontier-memory-cookie-store-verifier.sif \
      containers/frontier-memory-cookie-store-verifier.def
    ;;
  cookie-store)
    build_and_check containers/frontier-memory-cookie-store-verifier.sif \
      containers/frontier-memory-cookie-store-verifier.def
    apptainer exec --fakeroot containers/frontier-memory-cookie-store-verifier.sif \
      sh -lc 'test "$(git -C /app rev-parse HEAD)" = "b5addb64f0161ff6bfe94c124ef76f6a1fba5254" && git -C /app cat-file -e HEAD:tests/conftest.py'
    ;;
  *)
    echo "BUILD_SCOPE must be both or cookie-store" >&2
    exit 2
    ;;
esac
