You are checking one claim from a software-engineering memory note against excerpts from earlier agent work logs.

Each excerpt header gives the run's recorded outcome (PASS or FAIL). That outcome is context only and does not show whether the claim is right.

Work in this order.

1. Quote. Copy the shortest span from the excerpts (at most 40 words) that is about the same thing as the claim: the same tool, setting, file, entity, or step. If no excerpt is about the same thing, use an empty string.
2. Compare. Check each specific value, identifier, flag, and directive in the claim against the quoted span. Specific values include numbers, backticked names, on/off or enabled/disabled style flags, and directives such as "use X" or "do not use X" or "always" or "never".
3. Verdict.
   - "contradicted": the excerpts state a different value, identifier, flag, or directive for the same thing than the claim does.
   - "supported": the excerpts state the same specific values, identifiers, flags, and directives for the same thing.
   - "insufficient": no excerpt addresses the same thing with that specific detail, or there are no excerpts.

Rules:
- Use only the excerpts. Do not use outside knowledge about the software.
- A difference in wording alone is not a contradiction.
- A claim that is more general than the excerpt is not a contradiction.
- An excerpt that is silent about a specific value is "insufficient", not "contradicted".

Reply with one JSON object and nothing else:
{"quote": "<the span, or an empty string>", "verdict": "supported" | "contradicted" | "insufficient", "reason": "<one short sentence, at most 25 words>"}

CLAIM (a note from a memory file):
<<<CLAIM
{{CLAIM}}
CLAIM>>>

EXCERPTS:
{{EVIDENCE}}
