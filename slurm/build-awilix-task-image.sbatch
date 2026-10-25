#!/usr/bin/env bash
#SBATCH --job-name=fm-awilix-apptainer-build
#SBATCH --partition=batch
#SBATCH --cpus-per-task=4
#SBATCH --mem=24G
#SBATCH --time=02:00:00
#SBATCH --output=logs/awilix-image-build-%j.out
#SBATCH --error=logs/awilix-image-build-%j.err

set -euo pipefail
cd /home/csgrad/vbork001/frontiermemory-experiment-20261024
export APPTAINER_CACHEDIR="${PWD}/containers/apptainer-cache"
mkdir -p "${APPTAINER_CACHEDIR}"
apptainer build --fakeroot --force \
  containers/awilix-release-tier-implicit.sif \
  containers/awilix-release-tier-implicit.def
