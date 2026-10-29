#!/usr/bin/env bash
#SBATCH --job-name=fm-codex-ollama
#SBATCH --partition=vcggpu
#SBATCH --constraint=rtx3090
#SBATCH --gres=gpu:2
#SBATCH --cpus-per-task=8
#SBATCH --mem=96G
#SBATCH --time=02:30:00
#SBATCH --output=logs/codex-ollama-%j.out
#SBATCH --error=logs/codex-ollama-%j.err
# Generic Codex CLI (0.157.0-alpha.11.1) + local Ollama trial. Model qwen3.8:27b-mtp-q4_K_M, num_ctx 65536,
# reasoning effort medium. No OpenAI or ChatGPT credentials.
# Env (forwarded by sbatch): TASK (build-word2vec-pipeline default, or dapt-intrusion-detection-workflow-learning),
# TRIAL_ORDER (A/B tokens, default A), FROZEN_MEMORY_DIR and EXPECTED_MEMORY_DIGEST (needed for B).
# See scripts/run_codex_ollama_trial.sh for the full contract.
set -euo pipefail
cd /home/csgrad/vbork001/frontiermemory-experiment-20261024
exec bash scripts/run_codex_ollama_trial.sh
