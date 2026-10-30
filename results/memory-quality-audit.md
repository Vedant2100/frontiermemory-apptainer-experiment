# Memory-quality audit

Date: 2026-10-30. Measurement only, does not feed back into any arm.
Script: `scripts/audit_memory_quality.py`. Git HEAD: `0ff5cf9`.
Counts and rates only. No memory, lesson, topic or trajectory text is reported.

| Arm | Topic files | Units | Governable | Technical | Code units | Code >12 lines | R-artifacts | Resolvable-cited share (governable) | Grounded, cited evidence | Grounded, BM25 evidence | Grounded, all technical | Vacuous technical |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| M2 (frozen-v5) | 324 | 13727 | 11326 | 8055 | 115 | 31 | 27 | 2386/11326 (21.1%) | 778/1936 (40.2%) | 3562/6111 (58.3%) | 4347/8055 (54.0%) | 574 |
| M3 (frozen-v5-fullindex) | 324 | 13727 | 11326 | 8055 | 115 | 31 | 27 | 2386/11326 (21.1%) | 778/1936 (40.2%) | 3562/6111 (58.3%) | 4347/8055 (54.0%) | 574 |
| R25 (frozen-r25) | 116 | 4756 | 3904 | 2637 | 58 | 11 | 11 | 938/3904 (24.0%) | 335/720 (46.5%) | 1178/1915 (61.5%) | 1515/2637 (57.5%) | 216 |

Notes:
- Units = all parsed units, headings included. Governable = non-heading units. Technical = governable units where `rules.concrete_technical_assertion` holds. Code >12 lines counts raw lines inside fences; R-artifacts use the non-blank rule in `rules.r_artifact`.
- Grounding is the A2 rule (`grounding.grounding`) over all technical units, including R-artifact code blocks. Evidence is the cited steps when citations resolve, otherwise the top-3 BM25 steps in the topic's group. Vacuous = technical units with no concrete tokens, counted as grounded.
- M3 topic files are byte-identical to M2's (324 files, same names and SHA-256 digests), so M3 reuses the M2 audit and is not recounted. Only MEMORY.md differs (M3 has the appended complete index).
- R25 evidence: `results/memory-generation-r25/` has no `evidence/` directory. Its `evidence-index.json` matches v5's content, so R25 reads `results/memory-generation-v5/evidence/` with its own `groups.json`.
- Runtime: 7.3 s.
