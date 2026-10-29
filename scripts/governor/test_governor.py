"""Unit and corpus tests for the governor. Run: python scripts/governor/test_governor.py

Corpus tests read memory/frozen-v5-fullindex only. They do not read data/, tasks, or trial results.
"""

from __future__ import annotations

import json
import random
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from common import EVIDENCE_DIR, EVIDENCE_INDEX, GROUPS, M3_INDEX, M3_TOPICS, read_topic, topic_files  # noqa: E402
from evidence import BM25Index, CorpusEvidence, parse_steps, tokenize  # noqa: E402
from index_logic import build_complete_index, split_index, title_of  # noqa: E402
from judge import parse_reply, render_prompt  # noqa: E402
from perturb import applicable, file_identifier_pool  # noqa: E402
from rules import concrete_technical_assertion, r_artifact  # noqa: E402
from segment import parse, reassemble  # noqa: E402


class SegmentTests(unittest.TestCase):
    def roundtrip(self, text: str) -> None:
        self.assertEqual(reassemble(parse(text)), text)

    def test_roundtrip_small_inputs(self):
        for text in ["", "\n", "a", "a\n", "# H\n\n- x\n  cont\n- y\n\n1. one\n2. two\n",
                     "```markdown\n# T\n- a\n```\n", "```markdown\n# T\n- a\n", "para\n---\n***\n"]:
            self.roundtrip(text)

    def test_units_and_kinds(self):
        text = "# Title\n\nSome text\nmore text\n\n- item `a_b`\n  continued\n  - nested one\n1. first\n\n```bash\nls\n```\n"
        doc = parse(text)
        kinds = [u.kind for u in doc.units()]
        self.assertEqual(kinds, ["heading", "paragraph", "bullet", "bullet", "numbered", "code"])
        bullet = doc.units()[2]
        self.assertEqual(len(bullet.lines), 2)  # continuation belongs to its item
        self.assertEqual(doc.units()[5].code_nonblank, 1)

    def test_citations_attached(self):
        doc = parse("- claim inputs/t0012.json#step=3 and inputs/t0040.jsonl#step=7\n")
        self.assertEqual(doc.units()[0].citations, [("t0012.json", 3), ("t0040.jsonl", 7)])

    def test_removal_keeps_headings_and_drops_blank_doubling(self):
        text = "# H\n\n- a\n\n- b\n\n## S\n\n- c\n"
        doc = parse(text)
        bullets = [u.uid for u in doc.units() if u.kind == "bullet"]
        out = reassemble(doc, keep=[u.uid for u in doc.units() if u.uid not in bullets[:1]])
        self.assertEqual(out, "# H\n\n- b\n\n## S\n\n- c\n")
        out_all_removed = reassemble(doc, keep=[])
        self.assertEqual(out_all_removed, "# H\n\n## S\n")

    def test_code_block_never_split(self):
        text = "- x\n```\nline1\n\nline2\n```\n- y\n"
        units = parse(text).units()
        self.assertEqual([u.kind for u in units], ["bullet", "code", "bullet"])
        self.assertEqual(units[1].code_nonblank, 2)


class RuleTests(unittest.TestCase):
    def test_r_artifact_threshold(self):
        twelve = "```\n" + "\n".join(f"x{i}" for i in range(12)) + "\n```\n"
        thirteen = "```\n" + "\n".join(f"x{i}" for i in range(13)) + "\n```\n"
        self.assertFalse(r_artifact(parse(twelve).units()[0]))
        self.assertTrue(r_artifact(parse(thirteen).units()[0]))

    def test_concrete_predicate(self):
        def concrete(text):
            return concrete_technical_assertion(parse(text).units()[0])
        self.assertFalse(concrete("- Prefer short, plain explanations.\n"))
        self.assertTrue(concrete("- Use a timeout of 30 seconds.\n"))
        self.assertTrue(concrete("- Call `load_module` first.\n"))
        self.assertTrue(concrete("- Run pytest -q before submitting.\n"))
        self.assertFalse(concrete("- See inputs/t0001.json#step=4 for the reasoning.\n"))


class BM25Tests(unittest.TestCase):
    def test_ranking_prefers_matching_term(self):
        docs = [("t1", 1, tokenize("alpha beta")), ("t2", 1, tokenize("gamma delta")),
                ("t3", 1, tokenize("alpha alpha alpha"))]
        index = BM25Index(docs)
        top = index.top(tokenize("alpha"), 3)
        self.assertEqual([index.keys[i][0] for i in top][:2], ["t3", "t1"])
        self.assertEqual(index.top(tokenize("zzz"), 3), [])

    def test_tie_break_is_deterministic(self):
        docs = [("t2", 1, tokenize("x y")), ("t1", 1, tokenize("x y"))]
        index = BM25Index(docs)
        self.assertEqual([index.keys[i] for i in index.top(tokenize("x"), 2)], [("t1", 1), ("t2", 1)])


class IndexTests(unittest.TestCase):
    def test_m3_index_regenerates_byte_identically(self):
        text = M3_INDEX.read_text(encoding="utf-8")
        body, _ = split_index(text)
        topics = {p.name: read_topic(p) for p in topic_files(M3_TOPICS)}
        self.assertEqual(build_complete_index(body, topics), text)

    def test_title_rule(self):
        self.assertEqual(title_of("# Alpha\nbody"), "Alpha")
        self.assertEqual(title_of("```markdown\n## Beta: x\n"), "Beta: x")


class JudgeParseTests(unittest.TestCase):
    def test_parse_reply(self):
        self.assertEqual(parse_reply('{"quote":"q","verdict":"supported","reason":"ok"}'),
                         ("supported", "ok", "q"))
        self.assertEqual(parse_reply('<think>x</think>{"quote":"","verdict":"insufficient","reason":"r"}')[0],
                         "insufficient")
        self.assertIsNone(parse_reply('{"verdict":"maybe","reason":"x","quote":""}'))
        self.assertIsNone(parse_reply('{"verdict":"supported","reason":"x"}'))
        self.assertIsNone(parse_reply("not json"))
        self.assertIsNone(parse_reply('["supported"]'))

    def test_prompt_render(self):
        out = render_prompt("A {{CLAIM}} B {{EVIDENCE}}", "claim", [])
        self.assertIn("claim", out)
        self.assertIn("no excerpts available", out)


class DetectabilityTests(unittest.TestCase):
    def test_changed_tokens_and_detectable(self):
        from perturb import changed_tokens, detectable
        original = "- Keep 5 workers in `alpha_one`.\n"
        perturbed = "- Keep 8 workers in `alpha_one`.\n"
        self.assertEqual(changed_tokens(original, perturbed), ["5"])
        self.assertTrue(detectable(original, perturbed, "the run used 5 workers"))
        self.assertFalse(detectable(original, perturbed, "the run used 50 workers"))


class PerturbTests(unittest.TestCase):
    def test_each_type_changes_text(self):
        text = "- Use `alpha_one` with 5 workers and set enabled.\n"
        unit = parse(text).units()[0]
        rng = random.Random(1)
        pool = ["alpha_one", "beta_two", "gamma_three"]
        out = applicable(unit, pool, rng)
        self.assertEqual(set(out), {"number", "flag", "identifier", "negation"})
        self.assertIn("8 workers", out["number"])
        self.assertIn("disabled", out["flag"])
        self.assertIn("Do not use", out["negation"])
        self.assertNotIn("alpha_one", out["identifier"])

    def test_citations_untouched(self):
        unit = parse("- Keep 3 steps per run inputs/t0001.json#step=3\n").units()[0]
        out = applicable(unit, [], random.Random(0))
        self.assertIn("inputs/t0001.json#step=3", out["number"])


class CorpusTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.evidence = CorpusEvidence(EVIDENCE_DIR, EVIDENCE_INDEX, GROUPS)

    def test_every_topic_roundtrips(self):
        for path in topic_files(M3_TOPICS):
            text = read_topic(path)
            self.assertEqual(reassemble(parse(text)), text, path.name)

    def test_steps_parse_and_match_index(self):
        for tid in list(self.evidence.files)[:50]:
            steps = self.evidence.trajectory_steps(tid)
            self.assertEqual(set(steps), self.evidence.available(tid))

    def test_cited_evidence_is_resolved_and_truncated(self):
        cited = 0
        for path in topic_files(M3_TOPICS)[:60]:
            for unit in parse(read_topic(path)).units():
                if unit.citations and self.evidence.resolvable(unit.citations):
                    method, excerpts = self.evidence.evidence_for(unit.citations, unit.text, path.stem)
                    self.assertEqual(method, "cited")
                    self.assertTrue(all(len(e.text) <= 2000 for e in excerpts))
                    self.assertTrue(all(e.outcome in ("PASS", "FAIL") for e in excerpts))
                    cited += 1
        self.assertGreater(cited, 0)

    def test_bm25_fallback_gives_at_most_three(self):
        path = topic_files(M3_TOPICS)[0]
        for unit in parse(read_topic(path)).units():
            if unit.governable and not self.evidence.resolvable(unit.citations):
                method, excerpts = self.evidence.evidence_for(unit.citations, unit.text, path.stem)
                self.assertIn(method, ("bm25", "none"))
                self.assertLessEqual(len(excerpts), 3)
                break


class JudgeRetryTests(unittest.TestCase):
    """Bad JSON is retried up to MAX_ATTEMPTS, then recorded as insufficient with bad_json=True."""

    def _server(self, replies):
        import http.server
        import threading
        state = {"i": 0}

        class Handler(http.server.BaseHTTPRequestHandler):
            def do_POST(self):
                self.rfile.read(int(self.headers["Content-Length"]))
                reply = replies[min(state["i"], len(replies) - 1)]
                state["i"] += 1
                body = json.dumps({"message": {"content": reply}}).encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, *args):
                pass

        server = http.server.HTTPServer(("127.0.0.1", 0), Handler)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        return server, state

    def test_retry_then_success(self):
        from judge import OllamaJudge, prompt_template
        server, state = self._server(["oops", '{"quote":"","verdict":"contradicted","reason":"r"}'])
        try:
            judge = OllamaJudge(f"http://127.0.0.1:{server.server_port}/api/chat", "m")
            result = judge.judge(prompt_template()[0], "claim", [])
        finally:
            server.shutdown()
        self.assertEqual((result.verdict, result.attempts, result.bad_json), ("contradicted", 2, False))

    def test_all_attempts_bad_is_flagged_insufficient(self):
        from judge import MAX_ATTEMPTS, OllamaJudge, prompt_template
        server, state = self._server(['{"verdict":"maybe"}'])
        try:
            judge = OllamaJudge(f"http://127.0.0.1:{server.server_port}/api/chat", "m")
            result = judge.judge(prompt_template()[0], "claim", [])
        finally:
            server.shutdown()
        self.assertEqual(result.verdict, "insufficient")
        self.assertTrue(result.bad_json)
        self.assertEqual(result.attempts, MAX_ATTEMPTS)
        self.assertEqual(state["i"], MAX_ATTEMPTS)


class GroundingTests(unittest.TestCase):
    def test_tokens_extracted(self):
        from grounding import concrete_tokens
        text = "- Set `max_depth` to 12 and see inputs/t0042.json#step=7 at step 3, v2.1 `x-y`.\n"
        tokens = concrete_tokens(text)
        self.assertEqual(tokens.backticked, ("max_depth", "x-y"))
        self.assertEqual(tokens.numbers, ("12",))

    def test_list_marker_and_identifiers_excluded(self):
        from grounding import concrete_tokens
        self.assertEqual(concrete_tokens("3. Plain words only.\n").numbers, ())
        self.assertEqual(concrete_tokens("- Use t0042 and py3.11 and file_2.txt\n").numbers, ())

    def test_case_sensitive_backticks(self):
        from grounding import grounding
        unit = parse("- Call `Foo` once.\n").units()[0]
        self.assertFalse(grounding(unit, ["call foo once"])[0])
        self.assertTrue(grounding(unit, ["we call `Foo` once"])[0])

    def test_numbers_token_match(self):
        from grounding import grounding
        unit = parse("- Keep 5 workers.\n").units()[0]
        self.assertTrue(grounding(unit, ["used 5 workers"])[0])
        self.assertFalse(grounding(unit, ["used 50 workers"])[0])
        self.assertFalse(grounding(unit, ["used 15 workers"])[0])

    def test_vacuous_when_no_tokens(self):
        from grounding import grounding
        unit = parse("- Compare the outputs carefully.\n").units()[0]
        self.assertEqual(grounding(unit, []), (True, 0))


if __name__ == "__main__":
    unittest.main(verbosity=1)
