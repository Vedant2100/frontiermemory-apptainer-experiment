#!/usr/bin/env bash
#SBATCH --job-name=fm-customer-delivery-images
#SBATCH --partition=batch
#SBATCH --cpus-per-task=4
#SBATCH --mem=24G
#SBATCH --time=03:00:00
#SBATCH --output=logs/customer-delivery-images-%j.out
#SBATCH --error=logs/customer-delivery-images-%j.err
# CPU-only builds of the agent and verifier SIFs for customer-delivery-contextual-preferences (official v1.1 image).
# Refuses to overwrite existing SIFs. The registry pull needs network; compute-time grading does not.
set -euo pipefail
cd /home/csgrad/vbork001/frontiermemory-experiment-20261024
export APPTAINER_CACHEDIR="${PWD}/containers/apptainer-cache"
mkdir -p "${APPTAINER_CACHEDIR}" logs
for sif in containers/customer-delivery-contextual-preferences.sif containers/customer-delivery-contextual-preferences-verifier.sif; do
  if [[ -e "${sif}" ]]; then echo "refusing to overwrite ${sif}" >&2; exit 2; fi
done
apptainer version
apptainer build --fakeroot containers/customer-delivery-contextual-preferences.sif containers/customer-delivery-contextual-preferences.def
apptainer build --fakeroot containers/customer-delivery-contextual-preferences-verifier.sif containers/customer-delivery-contextual-preferences-verifier.def
sha256sum containers/customer-delivery-contextual-preferences.sif containers/customer-delivery-contextual-preferences-verifier.sif
