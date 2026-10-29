#!/usr/bin/env bash
#SBATCH --job-name=fm-w2v-codex-ollama
#SBATCH --partition=vcggpu
#SBATCH --constraint=rtx3090
#SBATCH --gres=gpu:2
#SBATCH --cpus-per-task=8
#SBATCH --mem=96G
#SBATCH --time=02:00:00
#SBATCH --output=logs/word2vec-codex-ollama-%j.out
#SBATCH --error=logs/word2vec-codex-ollama-%j.err
# Codex CLI (0.157.0-alpha.11.1) against a local Ollama server started in this GPU job.
# Model qwen3.8:27b-mtp-q4_K_M, num_ctx 65536, reasoning effort medium. No OpenAI or ChatGPT credentials.
# Env (optional, forwarded by sbatch): TRIAL_ORDER (A/B tokens, default A), FROZEN_MEMORY_DIR and
# EXPECTED_MEMORY_DIGEST (needed for B), TASK (default build-word2vec-pipeline). See
# scripts/run_codex_ollama_word2vec_trial.sh for the full contract.
set -euo pipefail
cd /home/csgrad/vbork001/frontiermemory-experiment-20261024
exec bash scripts/run_codex_ollama_word2vec_trial.sh
