import hashlib
import hmac
import json
import os
import pathlib
import sqlite3
import stat
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from http.server import BaseHTTPRequestHandler, HTTPServer

from testgate import config, githubapp, run, runner

SECRET = "unit-secret"
ROOT = pathlib.Path(__file__).resolve().parent.parent
DIFF = "diff --git a/a.py b/a.py\n--- a/a.py\n+++ b/a.py\n@@ -1 +1,2 @@\n x\n+y\n"
PR_RESPONSE = {
    "repo": "alice/r", "pr": 3, "scope": "pr", "commit": None, "title": "T", "body": "B", "state": "open",
    "base_ref": "main", "head_ref": "feat", "head_sha": "h" * 40,
    "files": [{"path": "a.py", "status": "modified", "additions": 1, "deletions": 0, "diff_included": True}],
    "diff": DIFF, "truncated": False,
}


class FakeApp(BaseHTTPRequestHandler):
    log = []
    behavior = {"pr_status": 200, "comment_status": 200}

    def log_message(self, *args):
        pass

    def do_POST(self):
        body = self.rfile.read(int(self.headers["content-length"]))
        ts = self.headers.get("x-hermes-timestamp", "")
        expected = "sha256=" + hmac.new(SECRET.encode(), f"{ts}.".encode() + body, hashlib.sha256).hexdigest()
        if not hmac.compare_digest(self.headers.get("x-hermes-signature", ""), expected):
            return self.reply(401, {"error": "invalid_signature"})
        payload = json.loads(body)
        FakeApp.log.append((self.path, payload))
        if self.path == "/api/pr":
            status = FakeApp.behavior["pr_status"]
            data = dict(PR_RESPONSE, commit=payload.get("commit"), scope="commit" if payload.get("commit") else "pr")
            return self.reply(status, data if status == 200 else {"error": "not_found"})
        if self.path == "/api/comment":
            status = FakeApp.behavior["comment_status"]
            return self.reply(status, {"ok": True, "url": "https://github.com/alice/r/pull/3#issuecomment-9", "commentId": 9, "duplicate": False} if status == 200 else {"error": "github_error"})
        if self.path == "/api/report":
            status = FakeApp.behavior.get("report_status", 200)
            return self.reply(status, {"ok": True, "url": "https://w.example.dev/r/" + "A" * 43, "expiresAt": 1, "duplicate": False} if status == 200 else {"error": "upload_failed"})
        if self.path == "/api/comment/update":
            status = FakeApp.behavior.get("update_status", 200)
            return self.reply(status, {"ok": True, "url": "https://github.com/alice/r/pull/3#issuecomment-9", "commentId": payload["commentId"]} if status == 200 else {"error": "github_error"})
        return self.reply(404, {"error": "nope"})

    def reply(self, status, data):
        raw = json.dumps(data).encode()
        self.send_response(status)
        self.send_header("content-type", "application/json")
        self.send_header("content-length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)


def final_comments():
    """결과를 싣는 코멘트 요청들. 확인 코멘트(-ack) 게시는 제외하고, 확인 코멘트 수정과 대체 게시를 모은다."""
    return [p for path, p in FakeApp.log
            if path == "/api/comment/update" or (path == "/api/comment" and not p["deliveryId"].endswith("-ack"))]


FAKE_CLAUDE = """#!/usr/bin/env python3
import json, os, sys
sys.stdin.read()
if os.environ.get("FAKE_MODE") == "fail":
    sys.stderr.write("boom"); sys.exit(3)
print(json.dumps({"is_error": False, "structured_output": json.loads(os.environ["FAKE_OUTPUT"]), "total_cost_usd": 0.01, "duration_ms": 5, "modelUsage": {"m": {}}}))
"""
GOOD = {"mode": "evaluate", "summary": "요약", "notes": "", "changes": [
    {"path": "a.py", "change_summary": "c", "tested": "yes", "evidence_quote": "a.py 를 확인했다", "request": "", "scenarios": []}]}


class Base(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = HTTPServer(("127.0.0.1", 0), FakeApp)
        cls.port = cls.server.server_address[1]
        threading.Thread(target=cls.server.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()

    def setUp(self):
        FakeApp.log = []
        FakeApp.behavior = {"pr_status": 200, "comment_status": 200}
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.home = pathlib.Path(self.tmp.name)
        claude = self.home / "claude"
        claude.write_text(FAKE_CLAUDE)
        claude.chmod(claude.stat().st_mode | stat.S_IEXEC)
        self.claude = runner.ClaudeRunner(binary=str(claude))
        os.environ["FAKE_OUTPUT"] = json.dumps(GOOD)
        os.environ.pop("FAKE_MODE", None)
        self.addCleanup(lambda: [os.environ.pop(k, None) for k in ("FAKE_OUTPUT", "FAKE_MODE")])
        self.app = githubapp.GithubApp(f"http://127.0.0.1:{self.port}", SECRET, timeout=5)
        self.settings = dict(config.DEFAULTS, retention_days=30)

    def spool(self, delivery_id="d-1", **overrides):
        """controller가 쓰는 요청 파일(request.v1)을 만든다. commit, text, free, unsupported로 코멘트 원문을 짓는다."""
        commit, text = overrides.pop("commit", None), overrides.pop("text", "a.py 를 확인했다")
        free, unsupported = overrides.pop("free", False), overrides.pop("unsupported", None)
        body = "/qa " + ("free: " if free else "") + (f"[{commit}] " if commit else "") + text
        data = {"version": 1, "deliveryId": delivery_id, "route": "testgate", "repo": "alice/r", "pr": 3,
                "target": unsupported or "pull_request", "author": None, "body": body}
        data.update(overrides)
        folder = self.home / "controller" / "requests"
        folder.mkdir(parents=True, exist_ok=True)
        (folder / f"{delivery_id}.json").write_text(json.dumps(data))
        return folder / f"{delivery_id}.json"

    def request_path(self, delivery_id="d-1"):
        return self.home / "controller" / "requests" / f"{delivery_id}.json"

    def context_path(self, delivery_id="d-1"):
        return self.home / "controller" / "requests" / f"{delivery_id}.context.json"

    def execute(self, delivery_id="d-1", owners=("alice",), **kw):
        """두 번째 값은 옛 시험과의 호환용(세션 이름 변경 기록)이다. 이제 본 프로젝트는 세션을 모르므로 늘 비어 있다."""
        summary = run.execute(self.request_path(delivery_id), self.context_path(delivery_id), self.home, self.settings,
                              list(owners), self.claude, self.app, **kw)
        return summary, []


class GithubAppTest(Base):
    def test_signed_requests_and_context_mapping(self):
        ctx = self.app.fetch_context("alice/r", 3)
        self.assertEqual(FakeApp.log[0], ("/api/pr", {"repo": "alice/r", "pr": 3}))
        self.assertEqual(ctx["base_ref"], "main")
        self.assertEqual(ctx["files"][0]["path"], "a.py")
        self.assertIs(ctx["files"][0]["diff_included"], True)

    def test_commit_is_sent(self):
        ctx = self.app.fetch_context("alice/r", 3, "abc1234")
        self.assertEqual(FakeApp.log[0][1]["commit"], "abc1234")
        self.assertEqual(ctx["scope"], "commit")

    def test_wrong_secret_is_an_error_without_leaking(self):
        bad = githubapp.GithubApp(f"http://127.0.0.1:{self.port}", "wrong", timeout=5)
        with self.assertRaises(githubapp.GithubAppError) as ctx:
            bad.fetch_context("alice/r", 3)
        self.assertIn("401", str(ctx.exception))
        self.assertNotIn("wrong", str(ctx.exception))

    def test_connection_refused(self):
        dead = githubapp.GithubApp("http://127.0.0.1:1", SECRET, timeout=2)
        with self.assertRaises(githubapp.GithubAppError):
            dead.fetch_context("alice/r", 3)

    def test_missing_secret_is_rejected(self):
        with self.assertRaises(githubapp.GithubAppError):
            githubapp.GithubApp("http://x", "")

    def test_comment_returns_url(self):
        url = self.app.post_comment("alice/r", 3, "본문", "d-1")
        self.assertTrue(url.endswith("issuecomment-9"))
        self.assertEqual(FakeApp.log[0][1], {"repo": "alice/r", "pr": 3, "body": "본문", "deliveryId": "d-1"})

    def test_signature_helper(self):
        self.assertEqual(
            githubapp.sign_request("k", "100", b"{}"),
            "sha256=" + hmac.new(b"k", b"100.{}", hashlib.sha256).hexdigest(),
        )


class LoadRequestTest(Base):
    CONTRACT = ROOT / "contracts" / "request.v1.json"

    def test_contract_example_is_read(self):
        req = run.load_request(self.CONTRACT, ["acme"])
        self.assertEqual((req["repo"], req["pr"], req["commit"], req["free"], req["unsupported"]), ("acme/shop", 7, None, False, None))
        self.assertIn("음수 잔액", req["text"])

    def test_body_is_parsed_with_the_qa_grammar(self):
        self.spool(commit="abc1234", free=True, text="질문")
        req = run.load_request(self.request_path(), ["alice"])
        self.assertEqual((req["commit"], req["free"], req["text"]), ("abc1234", True, "질문"))

    def test_not_a_qa_command_is_none(self):
        for body in ("/qatest", "그냥 코멘트"):
            self.spool(body=body)
            self.assertIsNone(run.load_request(self.request_path(), ["alice"]))
            summary, _ = self.execute()
            self.assertEqual(summary["result"], "ignored")

    def test_rejects(self):
        with self.assertRaises(run.RunError):
            run.load_request(self.home / "missing.json", ["alice"])
        bad = [{"version": 2}, {"deliveryId": "../x"}, {"repo": "nope"}, {"repo": "bob/r"}, {"pr": 0}, {"pr": "3"},
               {"pr": True}, {"target": "commit"}, {"body": 5}]
        for i, override in enumerate(bad):
            self.spool(f"b{i}", **override)
            with self.assertRaises(run.RunError, msg=str(override)):
                run.load_request(self.request_path(f"b{i}"), ["alice"])

    def test_empty_allowed_owners_rejects_all(self):
        self.spool()
        with self.assertRaises(run.RunError):
            run.load_request(self.request_path(), [])


class ExecuteTest(Base):
    def test_success_end_to_end(self):
        self.spool()
        summary, _ = self.execute()
        self.assertEqual((summary["result"], summary["verdict"], summary["session"]), ("ok", "sufficient", "[PR3 - T #1]"))
        self.assertTrue(summary["comment"].endswith("issuecomment-9"))
        self.assertEqual(summary["report"], "saved")
        self.assertEqual(json.loads(run.result_line(summary)), {"version": 1, "status": "done", "session_name": "[PR3 - T #1]"})
        acks = [p for path, p in FakeApp.log if path == "/api/comment"]
        self.assertEqual([p["deliveryId"] for p in acks], ["d-1-ack"])
        self.assertIn("분석을 시작했습니다", acks[0]["body"])
        posted = final_comments()[0]
        self.assertEqual(posted["commentId"], 9, "확인 코멘트를 수정해서 결과를 싣는다")
        self.assertTrue(posted["body"].rstrip().endswith("세션: `[PR3 - T #1]`"))
        report = self.home / "testgate" / "reports" / "d-1.md"
        self.assertEqual(stat.S_IMODE(report.stat().st_mode), 0o600)
        self.assertEqual(report.read_text(encoding="utf-8"), posted["body"])
        self.assertEqual(json.loads((self.home / "testgate" / "reports" / "d-1.json").read_text())["result"]["mode"], "evaluate")

    def test_commit_in_session_name(self):
        self.spool(commit="abc1421511")
        summary, _ = self.execute()
        self.assertEqual(summary["session"], "[PR3 - T - abc1421511 #1]")

    def test_claude_failure_posts_generic_failure_comment_with_other_id(self):
        self.spool()
        os.environ["FAKE_MODE"] = "fail"
        summary, _ = self.execute()
        self.assertEqual(summary["result"], "failed")
        posted = final_comments()[0]
        self.assertEqual(posted["commentId"], 9, "실패 안내도 확인 코멘트를 수정해서 싣는다")
        self.assertIn("분석에 실패했습니다", posted["body"])
        self.assertNotIn("boom", posted["body"])
        self.assertFalse((self.home / "testgate" / "reports" / "d-1.md").exists())

    def test_pr_fetch_failure(self):
        self.spool()
        FakeApp.behavior["pr_status"] = 404
        summary, _ = self.execute()
        self.assertEqual(summary["result"], "failed")
        self.assertIn("404", summary["error"])

    def test_comment_failure_keeps_report(self):
        self.spool()
        FakeApp.behavior["comment_status"] = 502
        summary, _ = self.execute()
        self.assertEqual(summary["result"], "ok")
        self.assertEqual(summary["comment"], "failed")
        self.assertTrue((self.home / "testgate" / "reports" / "d-1.md").exists())

    def test_post_comments_off(self):
        self.spool()
        self.settings["post_comments"] = False
        summary, _ = self.execute()
        self.assertEqual(summary["comment"], "skipped")
        self.assertFalse([1 for path, _ in FakeApp.log if path.startswith("/api/comment")])

    def test_invalid_request_never_calls_github_or_claude(self):
        summary, _ = self.execute("nothing")
        self.assertEqual(summary["result"], "failed")
        self.assertEqual(FakeApp.log, [])

    def test_result_line_follows_the_contract(self):
        cases = [({"result": "ok", "session": "[PR3 - T #1]"}, ("done", "[PR3 - T #1]")),
                 ({"result": "failed", "session": "-"}, ("failed", None)),
                 ({"result": "ignored", "session": "-"}, ("ignored", None))]
        for summary, (status, name) in cases:
            line = run.result_line(summary)
            self.assertNotIn("\n", line)
            self.assertEqual(json.loads(line), {"version": 1, "status": status, "session_name": name})


class LoadAppTest(unittest.TestCase):
    def test_secret_comes_only_from_the_environment(self):
        app = run.load_app({"github_app_url": "http://x"}, {"TESTGATE_GITHUB_APP_SECRET": "from-env"})
        self.assertEqual(app.secret, "from-env")

    def test_missing_secret_names_the_variable_not_a_value(self):
        for env in ({}, {"TESTGATE_GITHUB_APP_SECRET": ""}):
            with self.assertRaises(githubapp.GithubAppError) as ctx:
                run.load_app({"github_app_url": "http://x"}, env)
            self.assertIn("TESTGATE_GITHUB_APP_SECRET", str(ctx.exception))

    def test_no_secret_in_config_defaults_and_no_secret_file_loader(self):
        self.assertNotIn("github_app_secret", config.DEFAULTS)
        with self.assertRaises(ImportError):
            __import__("testgate.secrets")


class CleanupTest(Base):
    def test_cleanup_removes_only_old_files(self):
        for sub in ("reports", "threads"):
            folder = self.home / "testgate" / sub
            folder.mkdir(parents=True)
            old, fresh = folder / "old.json", folder / "fresh.json"
            old.write_text("{}")
            fresh.write_text("{}")
            past = time.time() - 40 * 86400
            os.utime(old, (past, past))
        run.cleanup(self.home, 30)
        for sub in ("reports", "threads"):
            self.assertFalse((self.home / "testgate" / sub / "old.json").exists())
            self.assertTrue((self.home / "testgate" / sub / "fresh.json").exists())


if __name__ == "__main__":
    unittest.main()
