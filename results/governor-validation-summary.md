# Governor judge validation: attempt 1 (gate FAILED, governor not run)

Preregistration v1, section 2.6. Job 303211 (fm-governor-validate, vcggpu, 2x RTX 3090/A5000), run at 2026-10-29 09:37-09:58 PDT.
Outputs: `results/governor-run-303211/validation/` (validation-report.json, validation-units.jsonl; hashes and verdicts only).

## Result

| Measure | Value | Gate |
|---|---|---|
| Sensitivity (perturbed units judged `contradicted`) | 12/100 = **0.12** | >= 0.6 (FAIL) |
| Specificity (unperturbed units judged `supported` or `insufficient`) | 92/100 = **0.92** | >= 0.8 (pass) |

Original verdicts (100 units): supported 61, insufficient 31, contradicted 8.
Perturbed verdicts (100 units): supported 54, insufficient 34, contradicted 12.

Sensitivity by perturbation type (n, judged contradicted):
- number: 39, 0 (0.00)
- identifier: 41, 4 (0.10)
- negation: 15, 7 (0.47)
- flag: 5, 1 (0.20)

Bad-JSON flags: 0. Wall time: 1,226 s for 200 judge calls (about 6.1 s per call, sequential).

## Sample

- Eligible: 2,382 non-heading, non-R-artifact M3 units with at least one resolvable citation (all 2,382 use cited evidence).
- Sample: 100 drawn with seed 2027 from the sorted list, each with one applicable perturbation.
- Perturbation draw: identifier 41, number 39, negation 15, flag 5.

## Diagnostic (counts only, after the run)

For each perturbed unit, I checked whether the changed token occurs as a whole token in the cited excerpts:
- Present in cited evidence: 41 of 100. Of these, 3 were judged `contradicted` (about 7%).
- Absent from cited evidence: 59 of 100. The evidence does not show the changed element at all.

So the judge rarely calls a changed claim contradicted, even when the excerpts show the original value. A ceiling also applies to this design: the perturbed element is often not shown in the cited excerpts. The 0.6 sensitivity gate may not be reachable on this synthetic set with this evidence. This is an observation for the lead, not a fix. I did not revise the prompt.

## Model and inputs

- Judge model: `gemma3:27b` (Gemma 3, 27B, non-Qwen), Ollama library. Pulled on the login node over HTTPS into the shared store and checksum-verified.
  - Manifest sha256: `6be2e2ba6843b9255820e2de2cbbe75cfdef0294ac7a531572e654d6e0eefe7d`
  - Model layer: `sha256:3eb75691d2db8bb04109c517466bb10bc0e4f035227d1a46cbba2f1d8e6afa45`
  - Total download about 17.4 GB.
- Bundled Ollama in `containers/ollama.sif` reports 0.40.11. I did not test gemma4:26b, which may need a newer server.
- Judge prompt: `scripts/governor/judge_prompt.md`, sha256 `59e83a406b1f08b40d12609615cbb57422d18f02b0c0b3e48a71e78fef5578d2`.
- Settings: temperature 0, seed 2027, num_ctx 16384, JSON schema output, max 3 attempts.

## Status and next steps

- The gate failed, so `govern.py` was not run and no memory-G or memory-GR was produced.
- Per the plan, the prompt was not revised. The lead decides whether to allow the one permitted revision (synthetic set only).
- Full governor run cost, from the measured rate: 11,299 judged units (11,326 non-heading units minus 27 R-artifact), about 19 h sequential at 6.1 s per call. Parallel workers could cut this, but the speedup is unmeasured. This exceeds the 5 h threshold, so the lead should decide before running.

# Amendment A1: revised judge prompt and detectable validation set (both models FAILED the gate)

Jobs 303219 (gemma3:27b) and 303220 (qwen3.8:27b-mtp-q4_K_M), run concurrently, 2 GPUs each, 2026-10-29 ~10:00-10:21 PDT.
Reports: `results/governor-run-303219/validation/validation-a1-gemma3-27b.json` and
`results/governor-run-303220/validation/validation-a1-qwen3.8-27b-mtp-q4-K-M.json`.

Revised judge prompt sha256 `1b4a53b7eadbb876a199f8ca134fd4f3ddb0bcbc744164ae5359c533b1ad0930` (fields quote, verdict, reason; temperature 0; seed 2027; think off).
Validation set: 100 units, seed 2027, from the 2,382 units with resolvable citations. Each unit's changed token occurs as a whole token in its cited evidence (detectable). Same set for both models.
Perturbations: identifier 56, number 34, negation 5, flag 5.

| Model | Sensitivity | Specificity | Gate | Sens. by type (number / identifier / negation / flag) | Bad-JSON flags | Wall time |
|---|---|---|---|---|---|---|
| gemma3:27b | 0.16 | 0.85 | FAIL | 0.26 / 0.05 / 0.60 / 0.20 | 6 | 1,169 s |
| qwen3.8:27b-mtp-q4_K_M | 0.21 | 0.98 | FAIL | 0.47 / 0.07 / 0.20 / 0.00 | 0 | 831 s |

Selection (A1): neither model passes the gate, so no model is chosen. Per A1, arms G and GR are dropped from the confirmatory matrix, and the judge failure is reported as a finding. No govern run was made.

Throughput (both models, 4 workers, server parallel 4, 2 GPUs): about 4 s per call (qwen) and 5.5 s per call (gemma), effective. Technical units to judge: 8,028 of 11,299 non-R units (71%). Full judging at these rates is about 9-12 h, above the 8 h limit, so it would need sharding even if a model had passed.

# Amendment A2: deterministic grounding rule on the A1 set (gate FAILED; G and GR dropped for good)

Report: `results/governor-run-a2-validate/validation/validation-a2.json` (run locally, CPU only, no model).
Same 100 units and perturbations as A1.

| Measure | Value | Gate |
|---|---|---|
| Sensitivity (perturbed units dropped) | 62/100 = 0.62 | >= 0.6 (pass) |
| Specificity (original units kept) | 50/100 = 0.50 | >= 0.8 (FAIL) |

Sensitivity by type: number 0.74 (34), identifier 0.55 (56), negation 0.80 (5), flag 0.40 (5).

Originals: all 100 are technical. 4 have zero concrete tokens (vacuously grounded). 50 are dropped because at least one backticked span or number is absent from the cited evidence.
Diagnostic (counts only): all 50 dropped originals use cited evidence. They have 83 missing backticked spans and 16 missing numbers. Only 9 of the 50 would be grounded if the 2,000-character truncation were removed. So the failure is in the rule and the evidence, not in truncation.

Per A2, no revision is allowed. G and GR are dropped for good. No memory-G or memory-GR was produced.
