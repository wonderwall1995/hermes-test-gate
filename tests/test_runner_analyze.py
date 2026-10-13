import json
import os
import pathlib
import stat
import tempfile
import unittest

from testgate import analyze, knowledge, runner

FAKE = """#!/usr/bin/env python3
import json, os, sys
record = os.environ["FAKE_ARGS_FILE"]
open(record, "w").write(json.dumps({"argv": sys.argv[1:], "stdin": sys.stdin.read(), "cwd": os.getcwd()}))
mode = os.environ.get("FAKE_MODE", "ok")
if mode == "fail":
    sys.stderr.write("boom"); sys.exit(3)
if mode == "garbage":
    print("not json"); sys.exit(0)
if mode == "error":
    print(json.dumps({"is_error": True})); sys.exit(0)
if mode == "nostructured":
    print(json.dumps({"is_error": False, "result": "x"})); sys.exit(0)
out = json.loads(os.environ["FAKE_OUTPUT"])
print(json.dumps({"is_error": False, "structured_output": out, "total_cost_usd": 0.01, "duration_ms": 5,
                  "modelUsage": {"claude-x": {}}}))
"""

CONTEXT = {"title": "t", "body": "", "base_ref": "main", "scope": "pr", "head_sha": "abc",
           "files": [{"path": "a.py", "status": "modified", "additions": 1, "deletions": 0, "diff_included": True}],
           "diff": "diff --git a/a.py b/a.py\n+x\n", "truncated": False}
REQUEST = {"deliveryId": "d", "repo": "o/r", "pr": 7, "commit": None, "text": "a.py 의 로그를 확인했다"}
GOOD = {"mode": "evaluate", "summary": "요약", "notes": "", "changes": [
    {"path": "a.py", "change_summary": "c", "tested": "yes", "evidence_quote": "로그를 확인했다",
     "request": "", "scenarios": []}]}


class FakeClaudeCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.binary = pathlib.Path(self.tmp.name) / "claude"
        self.binary.write_text(FAKE)
        self.binary.chmod(self.binary.stat().st_mode | stat.S_IEXEC)
        self.record = pathlib.Path(self.tmp.name) / "record.json"
        os.environ["FAKE_ARGS_FILE"] = str(self.record)
        os.environ["FAKE_OUTPUT"] = json.dumps(GOOD)
        os.environ.pop("FAKE_MODE", None)
        self.addCleanup(lambda: [os.environ.pop(k, None) for k in ("FAKE_ARGS_FILE", "FAKE_OUTPUT", "FAKE_MODE")])

    def runner(self, **kw):
        return runner.ClaudeRunner(binary=str(self.binary), **kw)


class RunnerTest(FakeClaudeCase):
    def test_safe_flags_and_stdin(self):
        out, meta = self.runner(model="sonnet").run("SYS", "USER-PROMPT", {"type": "object"})
        rec = json.loads(self.record.read_text())
        argv = rec["argv"]
        self.assertEqual(rec["stdin"], "USER-PROMPT")
        self.assertEqual(argv[argv.index("--tools") + 1], "")
        for flag in ("-p", "--strict-mcp-config", "--disable-slash-commands", "--no-session-persistence"):
            self.assertIn(flag, argv)
        self.assertEqual(argv[argv.index("--setting-sources") + 1], "")
        self.assertEqual(argv[argv.index("--system-prompt") + 1], "SYS")
        self.assertEqual(argv[argv.index("--model") + 1], "sonnet")
        self.assertNotIn("--bare", argv)
        self.assertEqual(meta["cost_usd"], 0.01)
        self.assertEqual(out["mode"], "evaluate")

    def test_runs_in_empty_temp_dir(self):
        self.runner().run("S", "U", {})
        cwd = json.loads(self.record.read_text())["cwd"]
        self.assertIn("testgate-", cwd)

    def test_no_model_flag_by_default(self):
        self.runner().run("S", "U", {})
        argv = json.loads(self.record.read_text())["argv"]
        self.assertNotIn("--model", argv)
        self.assertNotIn("--effort", argv)

    def test_effort_flag(self):
        self.runner(model="claude-sonnet-5-5", effort="medium").run("S", "U", {})
        argv = json.loads(self.record.read_text())["argv"]
        self.assertEqual(argv[argv.index("--effort") + 1], "medium")
        self.assertEqual(argv[argv.index("--model") + 1], "claude-sonnet-5-5")

    def test_bad_effort_is_rejected(self):
        with self.assertRaises(runner.RunnerError):
            runner.ClaudeRunner(effort="ultra")

    def test_failures(self):
        for mode in ("fail", "garbage", "error", "nostructured"):
            os.environ["FAKE_MODE"] = mode
            with self.assertRaises(runner.RunnerError, msg=mode):
                self.runner().run("S", "U", {})

    def test_missing_binary(self):
        with self.assertRaises(runner.RunnerError):
            runner.ClaudeRunner(binary="/nonexistent/claude").run("S", "U", {})


class AnalyzeTest(FakeClaudeCase):
    def test_end_to_end(self):
        outcome = analyze.analyze(REQUEST, CONTEXT, knowledge.NullKnowledge(), self.runner())
        self.assertEqual(outcome["verdict"], "sufficient")
        self.assertEqual(outcome["session_name"], "[PR7 - t]")
        self.assertTrue(outcome["markdown"].rstrip().endswith("세션: `[PR7 - t]`"))

    def test_bad_output_shape_is_an_error(self):
        os.environ["FAKE_OUTPUT"] = json.dumps({"mode": "evaluate"})
        with self.assertRaises(analyze.AnalysisError):
            analyze.analyze(REQUEST, CONTEXT, knowledge.NullKnowledge(), self.runner())

    def test_fabricated_evidence_is_caught_end_to_end(self):
        bad = json.loads(json.dumps(GOOD))
        bad["changes"][0]["evidence_quote"] = "전부 통과했다"
        os.environ["FAKE_OUTPUT"] = json.dumps(bad)
        outcome = analyze.analyze(REQUEST, CONTEXT, knowledge.NullKnowledge(), self.runner())
        self.assertEqual(outcome["verdict"], "more_tests_needed")

    def test_oversized_prompt_is_refused(self):
        big = dict(CONTEXT, diff="diff --git a/a.py b/a.py\n" + "+x\n" * analyze.MAX_PROMPT_CHARS)
        with self.assertRaises(analyze.AnalysisError):
            analyze.analyze(REQUEST, big, knowledge.NullKnowledge(), self.runner())
        self.assertFalse(self.record.exists())


class KnowledgeTest(unittest.TestCase):
    def test_directory_knowledge(self):
        with tempfile.TemporaryDirectory() as d:
            root = pathlib.Path(d)
            (root / "diagnosis.json").write_text('{"feature": "로그인", "risks": ["a"]}')
            (root / "page.md").write_text("# 도메인 설명")
            (root / "skip.txt").write_text("ignored")
            (root / "bad.json").write_text("{broken")
            docs = knowledge.DirectoryKnowledge([d]).load({})
            self.assertEqual(sorted(x["id"] for x in docs), ["diagnosis.json", "page.md"])
            self.assertIn("로그인", next(x for x in docs if x["id"] == "diagnosis.json")["text"])

    def test_limits_and_missing_dir(self):
        with tempfile.TemporaryDirectory() as d:
            (pathlib.Path(d) / "a.md").write_text("가" * 100)
            (pathlib.Path(d) / "b.md").write_text("나" * 100)
            docs = knowledge.DirectoryKnowledge([d, "/nonexistent"], max_doc_chars=50, max_total_chars=80).load({})
            self.assertEqual(len(docs), 1)
            self.assertEqual(len(docs[0]["text"]), 50)

    def test_docs_reach_prompt_as_data(self):
        class Docs:
            def load(self, ctx):
                return [{"id": "diagnosis.json", "title": "d", "text": "도메인 사전"}]
        os.environ["FAKE_ARGS_FILE"] = "/dev/null"
        from testgate import prompt
        text = prompt.build_user_prompt(REQUEST, CONTEXT, Docs().load(CONTEXT))
        self.assertIn("name=reference:diagnosis.json", text)
        self.assertIn("도메인 사전", text)
        os.environ.pop("FAKE_ARGS_FILE", None)


if __name__ == "__main__":
    unittest.main()
