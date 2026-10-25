#!/usr/bin/env bash
#SBATCH --job-name=fm-awilix-serverdeps
#SBATCH --partition=batch
#SBATCH --cpus-per-task=2
#SBATCH --mem=12G
#SBATCH --time=01:00:00
#SBATCH --output=logs/awilix-serverdeps-%j.out
#SBATCH --error=logs/awilix-serverdeps-%j.err

set -euo pipefail
cd /home/csgrad/vbork001/frontiermemory-experiment-20261024
export APPTAINER_CACHEDIR="${PWD}/containers/apptainer-cache"
apptainer build --fakeroot --force \
  containers/awilix-release-tier-implicit-serverdeps.sif \
  containers/awilix-release-tier-implicit-serverdeps.def
