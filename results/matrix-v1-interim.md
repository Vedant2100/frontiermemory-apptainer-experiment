# Confirmatory matrix v1: interim results (2026-10-30)

Preregistration: `results/preregistration-v1.md` (tags `prereg-v1`, `-a4`, `-a5`). Arms: A0 (no memory), R25, M3; k=5 per arm; Latin order. Two of seven tasks are complete. **Interim results; no tests run yet** (the Holm-corrected analysis comes after all seven tasks finish).

## Results

| Task (job) | A0 strict | R25 strict | M3 strict | A0 cases (mean) | R25 cases (mean) | M3 cases (mean) |
|---|---|---|---|---|---|---|
| build-word2vec-pipeline (303281) | 0/5 | **5/5** | **5/5** | 0/6 | 6/6 | 6/6 |
| dapt-intrusion-detection-workflow-learning (303282) | 0/5 | 1/5 | 0/5 | 26.4/37 | 31.4/37 | 20.0/37 |

- Word2Vec: all A0 failures are `CONTRACT_COLLECTION_ERROR`, meaning the output does not meet the task's artifact contract.
- DAPT M3 per trial: 0 (NO_ARTIFACT), 31, 30, 21, 18. R25: 37, 32, 32, 24, 32. A0: 30, 21, 27, 24, 30.
- All 30 trials are valid. Each trial's arm label matches its seeded memory digest. R25's injected window matches `scripts/memory_exposure.py` ("match").

## Prediction from A4: falsified

A4 predicted that M3 would not beat A0 on Word2Vec by more than 1 of 5 trials. The result was 5/5 against 0/5. A4's premise, that agents never open memory files, came from 9 exploratory DAPT and cattrs trials and did not generalize.

## How the memory was used

How often agents opened memory files themselves (grep of `MEMORY.md`, or `cat` of topic files):

| Task | R25 trials that searched or opened memory | M3 trials that did |
|---|---|---|
| Word2Vec | 5/5 (opened a Word2Vec topic) | 5/5 (grepped `MEMORY.md` for "word2vec", then opened topics) |
| DAPT | 4/5 (opened a pcap-statistics topic) | 1/5 |

On Word2Vec, the M3 agents found Word2Vec topics by searching the full index in the file, although those topics were not in the injected window. Two paths are visible:
1. the injected window, which is always seen;
2. agent-initiated search, which happens when the task cues it.

On DAPT, the R25 agents opened the topic more often and scored higher than the M3 agents. This is descriptive; there is no causal claim at n=5.
