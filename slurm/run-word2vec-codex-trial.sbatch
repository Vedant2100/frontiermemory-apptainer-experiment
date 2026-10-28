#!/usr/bin/env bash
#SBATCH --job-name=fm-word2vec-codex-trial
#SBATCH --partition=batch
#SBATCH --cpus-per-task=4
#SBATCH --mem=8G
#SBATCH --time=01:00:00
#SBATCH --output=logs/word2vec-codex-trial-%j.out
#SBATCH --error=logs/word2vec-codex-trial-%j.err
# Codex CLI harness trial for the Word2Vec task (model gpt-reserve, reasoning medium).
# CPU-only: Codex calls the hosted API from inside the task agent container. No Ollama, no GPU.
# Env (optional, forwarded by sbatch): TRIAL_ORDER or CONDITION (default A), see
# scripts/run_codex_word2vec_trial.sh. Sequential trials, one Codex run and one nop grading each.
set -euo pipefail
cd /home/csgrad/vbork001/frontiermemory-experiment-20261024
exec bash scripts/run_codex_word2vec_trial.sh
