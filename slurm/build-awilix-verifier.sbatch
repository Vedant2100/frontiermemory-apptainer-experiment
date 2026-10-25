#!/usr/bin/env bash
#SBATCH --job-name=fm-awilix-verifier-build
#SBATCH --partition=batch
#SBATCH --cpus-per-task=4
#SBATCH --mem=24G
#SBATCH --time=02:00:00
#SBATCH --output=logs/awilix-verifier-build-%j.out
#SBATCH --error=logs/awilix-verifier-build-%j.err

set -euo pipefail
cd /home/csgrad/vbork001/frontiermemory-experiment-20261024
export APPTAINER_CACHEDIR="${PWD}/containers/apptainer-cache"
mkdir -p "${APPTAINER_CACHEDIR}"
apptainer build --fakeroot --force \
  containers/awilix-release-tier-implicit-verifier.sif \
  containers/awilix-release-tier-implicit-verifier.def
