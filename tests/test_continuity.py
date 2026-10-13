"""PR 대화 기록, 확인됨 이어받기, 자유 대화, 세션 순번을 시험한다."""

import json
import os
import pathlib
import stat
import subprocess
import tempfile
import threading
import unittest

from testgate import analyze, diffsource, knowledge, ledger, report, runner
from tests import test_run
from tests.test_run import Base, FakeApp

A = "diff --git a/a.py b/a.py\n--- a/a.py\n+++ b/a.py\n@@ -1 +1,2 @@\n x\n+y\n"
B = "diff --git a/b.py b/b.py\n--- a/b.py\n+++ b/b.py\n@@ -1 +1,2 @@\n x\n+z\n"


def file(path, included=True):
    return {"path": path, "status": "modified", "additions": 1, "deletions": 0, "diff_included": included}


def context(diff=A + B, files=("a.py", "b.py"), scope="pr", commit=None, title="제목"):
    return {"title": title, "body": "설명", "base_ref": "main", "scope": scope, "commit": commit, "head_sha": "h" * 40,
            "files": [file(p) for p in files], "diff": diff, "truncated": False}


def change(path, tested="yes", quote="", request=""):
    return {"path": path, "change_summary": f"{path} 요약", "tested": tested, "evidence_quote": quote,
            "request": request, "scenarios": []}


def output(changes, mode="evaluate"):
    return {"mode": mode, "summary": "요약", "changes": changes, "notes": ""}


LOGGING_CLAUDE = """#!/usr/bin/env python3
import json, os, sys
stdin = sys.stdin.read()
with open(os.environ["FAKE_LOG"], "a") as log:
    log.write(json.dumps({"argv": sys.argv[1:], "stdin": stdin}) + "\\n")
outputs = json.loads(os.environ["FAKE_OUTPUTS"])
index = sum(1 for _ in open(os.environ["FAKE_LOG"])) - 1
out = outputs[min(index, len(outputs) - 1)]
print(json.dumps({"is_error": False, "structured_output": out, "total_cost_usd": 0.01, "duration_ms": 5, "modelUsage": {"m": {}}}))
"""


class ClaudeMixin:
    def make_claude(self, outputs):
        folder = pathlib.Path(self._tmpdir.name)
        binary = folder / "claude"
        binary.write_text(LOGGING_CLAUDE)
        binary.chmod(binary.stat().st_mode | stat.S_IEXEC)
        self.log = folder / "calls.jsonl"
        self.log.write_text("")
        os.environ["FAKE_LOG"] = str(self.log)
        os.environ["FAKE_OUTPUTS"] = json.dumps(outputs)
        self.addCleanup(lambda: [os.environ.pop(k, None) for k in ("FAKE_LOG", "FAKE_OUTPUTS")])
        return runner.ClaudeRunner(binary=str(binary))

    def calls(self):
        return [json.loads(line) for line in self.log.read_text().splitlines() if line]


class LedgerTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.home = pathlib.Path(self.tmp.name)

    def test_sequence_and_idempotence(self):
        self.assertEqual(ledger.reserve(self.home, "o/r", 2, "d1"), 1)
        self.assertEqual(ledger.reserve(self.home, "o/r", 2, "d2"), 2)
        self.assertEqual(ledger.reserve(self.home, "o/r", 2, "d1"), 1)
        self.assertEqual(ledger.reserve(self.home, "o/r", 3, "d3"), 1)

    def test_file_name_supports_user_and_organization_owners(self):
        for owner in ("alice", "acme-org", "My.Org_1"):
            ledger.reserve(self.home, f"{owner}/repo.name", 7, "d")
            path = ledger.thread_path(self.home, f"{owner}/repo.name", 7)
            self.assertTrue(path.exists())
            self.assertEqual(path.parent, self.home / "testgate" / "threads")
            self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)

    def test_concurrent_reservations_get_distinct_numbers(self):
        seqs, errors = [], []
        def work(i):
            try:
                seqs.append(ledger.reserve(self.home, "o/r", 2, f"d{i}"))
            except Exception as exc:
                errors.append(exc)
        threads = [threading.Thread(target=work, args=(i,)) for i in range(12)]
        [t.start() for t in threads]
        [t.join() for t in threads]
        self.assertEqual(errors, [])
        self.assertEqual(sorted(seqs), list(range(1, 13)))

    def test_trimming_keeps_numbers_increasing(self):
        old = ledger.MAX_ENTRIES
        ledger.MAX_ENTRIES = 3
        self.addCleanup(lambda: setattr(ledger, "MAX_ENTRIES", old))
        for i in range(5):
            ledger.reserve(self.home, "o/r", 2, f"d{i}")
        data = ledger.load(ledger.thread_path(self.home, "o/r", 2), "o/r", 2)
        self.assertEqual([e["seq"] for e in data["entries"]], [3, 4, 5])
        self.assertEqual(ledger.reserve(self.home, "o/r", 2, "new"), 6)

    def test_corrupt_file_is_set_aside(self):
        path = ledger.thread_path(self.home, "o/r", 2)
        path.parent.mkdir(parents=True)
        path.write_text("{broken")
        self.assertEqual(ledger.reserve(self.home, "o/r", 2, "d1"), 1)
        self.assertTrue(pathlib.Path(str(path) + ".bad").exists())

    def test_finalize_and_title_history(self):
        ledger.reserve(self.home, "o/r", 2, "d1")
        ledger.finalize(self.home, "o/r", 2, "d1", {"status": "done", "kind": "evaluate", "session": "s"}, title="첫 이름")
        ledger.reserve(self.home, "o/r", 2, "d2")
        ledger.finalize(self.home, "o/r", 2, "d2", {"status": "failed"}, title="첫 이름")
        ledger.reserve(self.home, "o/r", 2, "d3")
        ledger.finalize(self.home, "o/r", 2, "d3", {"status": "done", "kind": "free"}, title="바뀐 이름")
        data = ledger.load(ledger.thread_path(self.home, "o/r", 2), "o/r", 2)
        self.assertEqual([t["title"] for t in data["titles"]], ["첫 이름", "바뀐 이름"])
        self.assertEqual([e["seq"] for e in ledger.done_entries(self.home, "o/r", 2)], [1, 3])


class CarryOverTest(unittest.TestCase):
    def fps(self, ctx):
        return ledger.file_fingerprints(ctx)

    def entry(self, ctx, tested, session="[PR2 #1]"):
        fps = self.fps(ctx)
        return {"seq": 1, "kind": "evaluate", "session": session,
                "files": {p: {"tested": t, "fp": fps.get(p), "evidence": f"{p} 확인", "summary": "요약", "session": session}
                          for p, t in tested.items()}}

    def test_yes_with_same_fingerprint_is_carried(self):
        ctx = context()
        carried, stale = ledger.carry_over([self.entry(ctx, {"a.py": "yes", "b.py": "no"})], ctx["files"], self.fps(ctx))
        self.assertEqual(list(carried), ["a.py"])
        self.assertEqual(stale, [])
        self.assertEqual(carried["a.py"]["session"], "[PR2 #1]")

    def test_changed_diff_is_stale_not_carried(self):
        old = context()
        new = context(diff=A.replace("+y", "+changed") + B)
        carried, stale = ledger.carry_over([self.entry(old, {"a.py": "yes", "b.py": "yes"})], new["files"], self.fps(new))
        self.assertEqual(list(carried), ["b.py"])
        self.assertEqual(stale, ["a.py"])

    def test_only_yes_is_carried(self):
        ctx = context()
        for status in ("partial", "no", "unclear"):
            carried, stale = ledger.carry_over([self.entry(ctx, {"a.py": status})], ctx["files"], self.fps(ctx))
            self.assertEqual((carried, stale), ({}, []), status)

    def test_scope_changes_the_fingerprint(self):
        pr = context()
        commit = context(scope="commit", commit="abc1234")
        self.assertNotEqual(self.fps(pr)["a.py"], self.fps(commit)["a.py"])
        self.assertNotEqual(self.fps(commit)["a.py"], self.fps(context(scope="commit", commit="def5678"))["a.py"])
        carried, _ = ledger.carry_over([self.entry(pr, {"a.py": "yes"})], commit["files"], self.fps(commit))
        self.assertEqual(carried, {})

    def test_newest_record_with_same_fingerprint_decides(self):
        ctx = context()
        yes, no = self.entry(ctx, {"a.py": "yes"}, "[PR2 #1]"), self.entry(ctx, {"a.py": "no"}, "[PR2 #2]")
        carried, stale = ledger.carry_over([yes, no], ctx["files"], self.fps(ctx))
        self.assertEqual((carried, stale), ({}, []))
        carried, _ = ledger.carry_over([no, yes], ctx["files"], self.fps(ctx))
        self.assertIn("a.py", carried)

    def test_file_without_visible_diff_is_never_carried(self):
        ctx = context()
        entry = self.entry(ctx, {"a.py": "yes"})
        hidden = dict(ctx, files=[file("a.py", included=False), file("b.py")])
        carried, _ = ledger.carry_over([entry], hidden["files"], self.fps(hidden))
        self.assertEqual(carried, {})

    def test_history_rendering_is_bounded(self):
        entries = [{"seq": i, "kind": "evaluate", "session": f"s{i}", "summary": "가" * 500,
                    "files": {"a.py": {"tested": "no", "request": "나" * 300}}} for i in range(1, 12)]
        text = ledger.render_history(entries, limit=5, max_chars=1000)
        self.assertLessEqual(len(text), 1000)
        free = ledger.render_history([{"seq": 1, "kind": "free", "session": "s", "question": "Q?", "answer": "A."}])
        self.assertIn("question: Q?", free)


class AnalyzeContinuityTest(ClaudeMixin, unittest.TestCase):
    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmpdir.cleanup)

    def request(self, text="a.py 를 확인했다", **kw):
        return dict({"deliveryId": "d", "repo": "o/r", "pr": 2, "commit": None, "text": text}, **kw)

    def test_carried_file_is_not_sent_to_claude_and_is_merged(self):
        ctx = context()
        first_claude = self.make_claude([output([change("a.py", "yes", "a.py 를 확인했다"), change("b.py", "no", request="b 테스트")])])
        first = analyze.analyze(self.request(), ctx, knowledge.NullKnowledge(), first_claude, name="[PR2 - 제목 #1]")
        self.assertEqual(first["verdict"], "more_tests_needed")
        entry = {"seq": 1, "kind": "evaluate", "session": "[PR2 - 제목 #1]", "summary": first["summary"], "files": first["files_record"]}

        second_claude = self.make_claude([output([change("b.py", "yes", "b.py 도 확인했다")])])
        second = analyze.analyze(self.request("b.py 도 확인했다"), ctx, knowledge.NullKnowledge(), second_claude,
                                 history=[entry], name="[PR2 - 제목 #2]")
        prompt = self.calls()[0]["stdin"]
        evaluate_block = prompt.split("name=files_to_evaluate")[1].split("<<<END")[0]
        self.assertIn("b.py", evaluate_block)
        self.assertNotIn("a.py", evaluate_block)
        self.assertIn("a.py", prompt.split("name=already_verified")[1].split("<<<END")[0])
        self.assertNotIn("diff --git a/a.py", prompt)
        self.assertIn("diff --git a/b.py", prompt)
        self.assertEqual(second["verdict"], "sufficient")
        changes = {c["path"]: c for c in second["result"]["changes"]}
        self.assertEqual(changes["a.py"]["carried_from"], "[PR2 - 제목 #1]")
        self.assertEqual(changes["a.py"]["evidence_quote"], "a.py 를 확인했다")
        self.assertIn("이전 요청 `[PR2 - 제목 #1]`에서 확인됨", second["markdown"])
        self.assertEqual(second["files_record"]["a.py"]["session"], "[PR2 - 제목 #1]")
        self.assertEqual(second["files_record"]["b.py"]["session"], "[PR2 - 제목 #2]")

    def test_all_carried_skips_claude(self):
        ctx = context()
        claude = self.make_claude([output([change("a.py", "yes", "a.py 를 확인했다"), change("b.py", "yes", "a.py 를 확인했다")])])
        first = analyze.analyze(self.request(), ctx, knowledge.NullKnowledge(), claude, name="[PR2 #1]")
        entry = {"seq": 1, "kind": "evaluate", "session": "[PR2 #1]", "files": first["files_record"]}
        before = len(self.calls())
        second = analyze.analyze(self.request("아무 말"), ctx, knowledge.NullKnowledge(), claude, history=[entry], name="[PR2 #2]")
        self.assertEqual(len(self.calls()), before)
        self.assertEqual((second["verdict"], second["mode"], second["meta"]["cost_usd"]), ("sufficient", "evaluate", 0))
        self.assertIn(analyze.ALL_VERIFIED_SUMMARY, second["markdown"])

    def test_changed_file_is_reevaluated_and_noted(self):
        old = context()
        claude = self.make_claude([output([change("a.py", "yes", "a.py 를 확인했다"), change("b.py", "yes", "a.py 를 확인했다")])])
        first = analyze.analyze(self.request(), old, knowledge.NullKnowledge(), claude, name="[PR2 #1]")
        entry = {"seq": 1, "kind": "evaluate", "session": "[PR2 #1]", "files": first["files_record"]}
        new = context(diff=A.replace("+y", "+바뀜") + B)
        claude2 = self.make_claude([output([change("a.py", "no", request="a 다시")])])
        second = analyze.analyze(self.request("다른 말"), new, knowledge.NullKnowledge(), claude2, history=[entry], name="[PR2 #2]")
        self.assertEqual(second["verdict"], "more_tests_needed")
        self.assertTrue(any("다시 확인이 필요한 파일: a.py" in n for n in second["notes"]))
        self.assertIn("다시 확인이 필요한 파일", second["markdown"])
        changes = {c["path"]: c for c in second["result"]["changes"]}
        self.assertNotIn("carried_from", changes["a.py"])
        self.assertEqual(changes["b.py"]["carried_from"], "[PR2 #1]")

    def test_history_reaches_the_prompt_as_data(self):
        ctx = context()
        claude = self.make_claude([output([change("a.py", "no"), change("b.py", "no")])])
        entry = {"seq": 1, "kind": "free", "session": "[PR2 #1]", "question": "이전 질문?", "answer": "이전 답."}
        analyze.analyze(self.request(), ctx, knowledge.NullKnowledge(), claude, history=[entry], name="[PR2 #2]")
        history_block = self.calls()[0]["stdin"].split("name=history")[1].split("<<<END")[0]
        self.assertIn("이전 질문?", history_block)

    def test_design_report_notes_carried_files(self):
        ctx = context()
        claude = self.make_claude([output([change("a.py", "yes", "a.py 를 확인했다"), change("b.py", "no")])])
        first = analyze.analyze(self.request(), ctx, knowledge.NullKnowledge(), claude, name="[PR2 #1]")
        entry = {"seq": 1, "kind": "evaluate", "session": "[PR2 #1]", "files": first["files_record"]}
        design = output([dict(change("b.py", "unclear"), scenarios=[{"title": "T", "steps": ["s"], "expected": "E"}])], mode="design")
        claude2 = self.make_claude([design])
        second = analyze.analyze(self.request("문서 뽑아줘"), ctx, knowledge.NullKnowledge(), claude2, history=[entry], name="[PR2 #2]")
        self.assertEqual(second["mode"], "design")
        self.assertIn("이전 요청 `[PR2 #1]`에서 확인되어 새 시나리오를 만들지 않았습니다", second["markdown"])


class FreeModeAnalyzeTest(ClaudeMixin, unittest.TestCase):
    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmpdir.cleanup)

    def request(self, **kw):
        return dict({"deliveryId": "d", "repo": "o/r", "pr": 2, "commit": None, "text": "이 PR이 뭘 해?", "free": True}, **kw)

    def test_diff_body_is_excluded_without_commit(self):
        claude = self.make_claude([{"answer": "답변입니다"}])
        out = analyze.analyze_free(self.request(), context(), knowledge.NullKnowledge(), claude, name="[PR2 #1]")
        prompt = self.calls()[0]["stdin"]
        self.assertNotIn("name=diff", prompt)
        self.assertNotIn("diff --git", prompt)
        self.assertIn("name=changed_files", prompt)
        self.assertIn("a.py", prompt)
        self.assertIn("name=message", prompt)
        self.assertEqual((out["mode"], out["verdict"]), ("free", "-"))
        self.assertTrue(out["markdown"].startswith("답변입니다"))
        self.assertTrue(out["markdown"].rstrip().endswith("세션: `[PR2 #1]`"))
        self.assertNotIn("## 변경별", out["markdown"])

    def test_diff_is_included_when_a_commit_is_given(self):
        claude = self.make_claude([{"answer": "x"}])
        ctx = context(scope="commit", commit="abc1234")
        analyze.analyze_free(self.request(commit="abc1234"), ctx, knowledge.NullKnowledge(), claude)
        self.assertIn("diff --git a/a.py", self.calls()[0]["stdin"])

    def test_uses_free_schema_and_free_system_prompt(self):
        claude = self.make_claude([{"answer": "x"}])
        analyze.analyze_free(self.request(), context(), knowledge.NullKnowledge(), claude)
        argv = self.calls()[0]["argv"]
        schema_arg = json.loads(argv[argv.index("--json-schema") + 1])
        self.assertEqual(schema_arg["required"], ["answer"])
        self.assertIn("free-form question", argv[argv.index("--system-prompt") + 1])

    def test_answer_is_escaped_and_capped(self):
        claude = self.make_claude([{"answer": "![x](https://e.test/?d=secret) @admin <script>" + "가" * 9000}])
        out = analyze.analyze_free(self.request(), context(), knowledge.NullKnowledge(), claude)
        self.assertNotIn("![", out["markdown"])
        self.assertNotIn("<script>", out["markdown"])
        self.assertNotIn("@admin", out["markdown"])
        self.assertLessEqual(len(out["answer"]), 6000)

    def test_bad_output_is_an_error(self):
        claude = self.make_claude([{"nope": 1}])
        with self.assertRaises(analyze.AnalysisError):
            analyze.analyze_free(self.request(), context(), knowledge.NullKnowledge(), claude)


class RunContinuityTest(Base):
    """래퍼 전체 흐름: 순번, 이름, 기록, 이어받기, 자유 대화."""

    def setUp(self):
        super().setUp()
        self.saved_pr = dict(test_run.PR_RESPONSE)
        self.addCleanup(lambda: test_run.PR_RESPONSE.clear() or test_run.PR_RESPONSE.update(self.saved_pr))
        folder = self.home
        binary = folder / "claude2"
        binary.write_text(LOGGING_CLAUDE)
        binary.chmod(binary.stat().st_mode | stat.S_IEXEC)
        self.log = folder / "calls.jsonl"
        self.log.write_text("")
        os.environ["FAKE_LOG"] = str(self.log)
        self.addCleanup(lambda: [os.environ.pop(k, None) for k in ("FAKE_LOG", "FAKE_OUTPUTS")])
        self.claude = runner.ClaudeRunner(binary=str(binary))

    def outputs(self, *outs):
        os.environ["FAKE_OUTPUTS"] = json.dumps(list(outs))

    def calls(self):
        return [json.loads(line) for line in self.log.read_text().splitlines() if line]

    def test_two_comments_get_distinct_numbered_sessions_and_second_sees_history(self):
        self.outputs(output([change("a.py", "no", request="a 해 주세요")]), output([change("a.py", "no", request="아직")]))
        self.spool("d-1")
        self.spool("d-2")
        first, _ = self.execute("d-1")
        second, renames = self.execute("d-2")
        self.assertEqual((first["session"], second["session"]), ("[PR3 - T #1]", "[PR3 - T #2]"))
        self.assertEqual(renames[0][-1], "[PR3 - T #2]")
        history_block = self.calls()[1]["stdin"].split("name=history")[1].split("<<<END")[0]
        self.assertIn("a 해 주세요", history_block)
        posts = [p for path, p in FakeApp.log if path == "/api/comment"]
        self.assertEqual([p["deliveryId"] for p in posts], ["d-1", "d-2"])
        self.assertTrue(posts[1]["body"].rstrip().endswith("세션: `[PR3 - T #2]`"))

    def test_verified_file_is_carried_to_the_next_comment_without_calling_claude(self):
        self.outputs(output([change("a.py", "yes", "a.py 를 확인했다")]))
        self.spool("d-1")
        self.spool("d-2", text="아무 말")
        self.execute("d-1")
        calls_after_first = len(self.calls())
        second, _ = self.execute("d-2")
        self.assertEqual(len(self.calls()), calls_after_first)
        self.assertEqual((second["result"], second["verdict"]), ("ok", "sufficient"))
        body = [p for path, p in FakeApp.log if path == "/api/comment"][1]["body"]
        self.assertIn("이전 요청 `[PR3 - T #1]`에서 확인됨", body)

    def test_changed_pr_title_is_used_by_later_sessions_only(self):
        self.outputs(output([change("a.py", "no")]))
        self.spool("d-1")
        self.spool("d-2")
        first, _ = self.execute("d-1")
        test_run.PR_RESPONSE["title"] = "새 이름"
        second, _ = self.execute("d-2")
        self.assertEqual(first["session"], "[PR3 - T #1]")
        self.assertEqual(second["session"], "[PR3 - 새 이름 #2]")
        data = ledger.load(ledger.thread_path(self.home, "alice/r", 3), "alice/r", 3)
        self.assertEqual([t["title"] for t in data["titles"]], ["T", "새 이름"])

    def test_free_comment_end_to_end_and_it_is_remembered(self):
        self.outputs({"answer": "이 PR은 로그인 잠금을 추가합니다."}, output([change("a.py", "no", request="r")]))
        self.spool("d-1", text="이 PR이 뭘 하는 거야?", free=True)
        free, _ = self.execute("d-1")
        self.assertEqual((free["result"], free["mode"], free["verdict"]), ("ok", "free", "-"))
        body = [p for path, p in FakeApp.log if path == "/api/comment"][0]["body"]
        self.assertTrue(body.startswith("이 PR은 로그인 잠금을 추가합니다."))
        self.assertNotIn("## 변경별", body)
        self.assertNotIn("diff --git", self.calls()[0]["stdin"])
        entry = ledger.done_entries(self.home, "alice/r", 3)[0]
        self.assertEqual((entry["kind"], entry["question"]), ("free", "이 PR이 뭘 하는 거야?"))
        # 이어지는 평가 요청에는 이전 질문과 답이 기록으로 들어간다. 하지만 free 응답은 이어받기 대상이 아니다.
        self.spool("d-2")
        second, _ = self.execute("d-2")
        history_block = self.calls()[1]["stdin"].split("name=history")[1].split("<<<END")[0]
        self.assertIn("이 PR은 로그인 잠금을 추가합니다.", history_block)
        self.assertEqual(second["verdict"], "more_tests_needed")

    def test_empty_free_comment_gets_a_fixed_hint_without_claude(self):
        self.outputs({"answer": "호출되면 안 됨"})
        self.spool("d-1", text="   ", free=True)
        summary, _ = self.execute("d-1")
        self.assertEqual((summary["result"], summary["mode"]), ("ok", "free"))
        self.assertEqual(self.calls(), [])
        body = [p for path, p in FakeApp.log if path == "/api/comment"][0]["body"]
        self.assertIn("/qa free: 질문", body)

    def test_organization_owner_works(self):
        test_run.PR_RESPONSE["repo"] = "acme-org/r"
        self.outputs(output([change("a.py", "no")]))
        self.spool("d-1", repo="acme-org/r")
        summary, _ = self.execute_with_owners("d-1", ["acme-org"])
        self.assertEqual(summary["result"], "ok")
        self.assertTrue((self.home / "testgate" / "threads" / "acme-org__r__3.json").exists())

    def execute_with_owners(self, delivery_id, owners):
        return self.execute(delivery_id, owners=owners)

    def test_failure_is_recorded_and_does_not_become_history(self):
        os.environ["FAKE_OUTPUTS"] = "not-json"   # runner가 파싱하는 출력이 아니라 fake 자체가 깨지게 한다
        self.spool("d-1")
        summary, _ = self.execute("d-1")
        self.assertEqual(summary["result"], "failed")
        self.assertEqual(ledger.done_entries(self.home, "alice/r", 3), [])
        data = ledger.load(ledger.thread_path(self.home, "alice/r", 3), "alice/r", 3)
        self.assertEqual(data["entries"][0]["status"], "failed")
        self.assertEqual([p["deliveryId"] for path, p in FakeApp.log if path == "/api/comment"], ["d-1-failed"])
        self.assertIn("#1", [p["body"] for path, p in FakeApp.log if path == "/api/comment"][0])


if __name__ == "__main__":
    unittest.main()
