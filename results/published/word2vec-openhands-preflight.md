# Word2Vec + OpenHands preflight

This is a sanitized preflight record for the exploratory FrontierMemory
`build-word2vec-pipeline` experiment. No benchmark score or memory-effect claim
is available yet.

## Verified

- The official task verifier ran unchanged in the Apptainer CPU image against
  the task's reference implementation and returned `PASS` (exit code 0).
- The task verifier files had matching before/after checksums.
- The verifier image contains the task's pinned package versions: gensim 4.3.2,
  nltk 3.9.1, numpy 1.24.3, pytest 8.4.1, and scipy 1.10.1.
- Harbor 0.24.0 resolved the existing OpenHands SDK adapter and its runtime
  preflight passed. The task copy changes only the container image references
  needed for Apptainer; the official task and verifier sources remain intact.
- The historical evidence screen uses the pinned FrontierMemory v1.0 corpus.
  Selected source trajectories and cited steps were checksum-checked and end in
  verifier `PASS`. The candidate evidence concerns preserving preprocessing
  schema across pipeline stages and following existing transformer integration
  patterns. It has moderate interface/pipeline relevance, but no direct
  Word2Vec or embedding-specific lesson. No memory was generated or injected.

## Not run

The no-memory agent did not start, so there are no edits, agent tests, model
tokens, task runtime, or original task score to report. The initial GPU job was
stopped before inference while Ollama was pulling the missing Devstral Small 2
weights. A later login-node preload was interrupted before completion. The
runner now refuses to download model weights inside an evaluation job.

Condition B was not run. No A/B comparison is available. This is not a
leaderboard result.

Raw trajectories, gated-corpus excerpts, generated evidence, and model files
remain local and are not included in this repository update.
