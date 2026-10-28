#!/usr/bin/env bash
#SBATCH --job-name=fm-dapt-images
#SBATCH --partition=batch
#SBATCH --cpus-per-task=4
#SBATCH --mem=16G
#SBATCH --time=01:00:00
#SBATCH --output=logs/dapt-apptainer-build-%j.out
#SBATCH --error=logs/dapt-apptainer-build-%j.err
# Builds the two new SIFs for dapt-intrusion-detection-workflow-learning.
# Refuses to overwrite existing images; needs network (apt, PyPI, docker://ubuntu).
set -euo pipefail
cd /home/csgrad/vbork001/frontiermemory-experiment-20261024
export APPTAINER_CACHEDIR="${PWD}/containers/apptainer-cache"
AGENT_SIF=containers/frontier-memory-dapt-agent.sif
VERIFIER_SIF=containers/frontier-memory-dapt-verifier.sif
for sif in "${AGENT_SIF}" "${VERIFIER_SIF}"; do
  if [[ -e "${sif}" ]]; then echo "refusing to overwrite ${sif}" >&2; exit 2; fi
done
apptainer version
apptainer build --fakeroot "${AGENT_SIF}" containers/frontier-memory-dapt-agent.def
apptainer exec --fakeroot "${AGENT_SIF}" /bin/bash -c \
  'test -s /root/packets.pcap && test -s /root/network_stats.csv && test -d /logs/verifier && python3 -c "import scapy,pandas,numpy; print(\"agent-python\", __import__(\"sys\").version.split()[0], \"scapy\", scapy.__version__, \"pandas\", pandas.__version__, \"numpy\", numpy.__version__)"'
apptainer build --fakeroot "${VERIFIER_SIF}" containers/frontier-memory-dapt-verifier.def
apptainer exec --fakeroot "${VERIFIER_SIF}" /bin/bash -c \
  'test -s /tests/test.sh && test -s /tests/test_outputs.py && test -d /logs/verifier && python3 -c "import pytest,scapy,pandas,numpy; print(\"verifier-python\", __import__(\"sys\").version.split()[0], \"pytest\", pytest.__version__)"'
sha256sum "${AGENT_SIF}" "${VERIFIER_SIF}"
ls -la "${AGENT_SIF}" "${VERIFIER_SIF}"
