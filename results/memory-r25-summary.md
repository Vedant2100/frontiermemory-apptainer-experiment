# Memory R25: stratified random 25% of the corpus (job 303206)

Confirmatory arm R25 (preregistration §1). This file records counts and hashes only.

| Item | Value |
|---|---|
| Selection | 168 of 674 trajectories (PASS 46, FAIL 122), stratified by outcome, seed 2027, `random.Random(seed).sample` over sorted ids within each outcome, largest-remainder allocation |
| Selected-id sha256 | `24d2518c94b904617017c53e6d817de0db27e58a1ed5a5a764d129f7b3988c97` |
| Pipeline | v5 map notes reused for the selected ids; v5 group, reduce and finalize code unchanged (same instruction, model `qwen3.8:27b-mtp-q4_K_M`, context 65,536, temperature 0.1); complete index added by `scripts/complete_memory_index.py`, the same code that produced M3 |
| Groups | 116 groups (91 singletons, largest has 10 notes) → 116 topic files |
| Reduce + finalize | 4,500 s + 150 s |
| Frozen | `memory/frozen-r25`, read-only |
| Official `check_memory` | ok |
| Folder digest | `75be173fb8b1332429bac0fc23323e9e62cd9fbf36c3e9740840d217461cf4c6` |
| `MEMORY.md` sha256 | `028d1905…`; index lists all 116 topics |
| Files / bytes | 117 / 455,910 |
