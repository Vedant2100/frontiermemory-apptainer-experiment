#!/usr/bin/env bash
#SBATCH --job-name=fm-awilix-images-v2
#SBATCH --partition=batch
#SBATCH --cpus-per-task=4
#SBATCH --mem=24G
#SBATCH --time=03:00:00
#SBATCH --output=logs/awilix-release-tier-images-%j.out
#SBATCH --error=logs/awilix-release-tier-images-%j.err
# CPU-only builds of the four awilix SIFs for the explicit and implicit release-tier tasks (official task image
# swe-bench-202605 kh70...@c574..., pulled from its public registry). Refuses to overwrite existing SIFs.
# Build-time network is used only for the registry pull; no npm install (dependencies come from the image).
set -euo pipefail
cd /home/csgrad/vbork001/frontiermemory-experiment-20261024
export APPTAINER_CACHEDIR="${PWD}/containers/apptainer-cache"
mkdir -p "${APPTAINER_CACHEDIR}" logs
for sif in containers/awilix-release-tier-explicit.sif containers/awilix-release-tier-implicit-v2.sif \
    containers/awilix-release-tier-explicit-verifier.sif containers/awilix-release-tier-implicit-verifier-v2.sif; do
  if [[ -e "${sif}" ]]; then echo "refusing to overwrite ${sif}" >&2; exit 2; fi
done
apptainer version
apptainer build --fakeroot containers/awilix-release-tier-explicit.sif containers/awilix-release-tier-explicit.def
apptainer build --fakeroot containers/awilix-release-tier-implicit-v2.sif containers/awilix-release-tier-implicit-v2.def
apptainer build --fakeroot containers/awilix-release-tier-explicit-verifier.sif containers/awilix-release-tier-explicit-verifier-v2.def
apptainer build --fakeroot containers/awilix-release-tier-implicit-verifier-v2.sif containers/awilix-release-tier-implicit-verifier-v2.def
sha256sum containers/awilix-release-tier-explicit.sif containers/awilix-release-tier-implicit-v2.sif \
  containers/awilix-release-tier-explicit-verifier.sif containers/awilix-release-tier-implicit-verifier-v2.sif
