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
            return self.reply(status, {"ok": True, "url": "https://github.com/alice/r/pull/3#issuecomment-9", "duplicate": False} if status == 200 else {"error": "github_error"})
        return self.reply(404, {"error": "nope"})

    def reply(self, status, data):
        raw = json.dumps(data).encode()
        self.send_response(status)
        self.send_header("content-type", "application/json")
        self.send_header("content-length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)


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
        data = {"deliveryId": delivery_id, "repo": "alice/r", "pr": 3, "commit": None, "text": "a.py 를 확인했다"}
        data.update(overrides)
        folder = self.home / "testgate" / "requests"
        folder.mkdir(parents=True, exist_ok=True)
        (folder / f"{delivery_id}.json").write_text(json.dumps(data))

    def execute(self, delivery_id="d-1", **kw):
        calls = []
        def fake_run(cmd, **k):
            calls.append(cmd)
            return subprocess.CompletedProcess(cmd, 0)
        summary = run.execute(delivery_id, self.home, self.settings, ["alice"], self.claude, self.app,
                              env={"HERMES_SESSION_ID": "sess_1"}, hermes_run=fake_run, **kw)
        return summary, calls


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
    def test_valid(self):
        self.spool()
        req = run.load_request(self.home, "d-1", ["alice"])
        self.assertEqual((req["repo"], req["pr"], req["commit"]), ("alice/r", 3, None))

    def test_rejects(self):
        cases = [
            ("../x", {}), ("a b", {}), ("", {}),
        ]
        for delivery_id, _ in cases:
            with self.assertRaises(run.RunError, msg=delivery_id):
                run.load_request(self.home, delivery_id, ["alice"])
        with self.assertRaises(run.RunError):
            run.load_request(self.home, "missing", ["alice"])
        bad = [{"repo": "nope"}, {"repo": "bob/r"}, {"pr": 0}, {"pr": "3"}, {"pr": True}, {"commit": "XYZ"},
               {"commit": "abc"}, {"text": 5}]
        for i, override in enumerate(bad):
            self.spool(f"b{i}", **override)
            with self.assertRaises(run.RunError, msg=str(override)):
                run.load_request(self.home, f"b{i}", ["alice"])

    def test_empty_allowed_owners_rejects_all(self):
        self.spool()
        with self.assertRaises(run.RunError):
            run.load_request(self.home, "d-1", [])


class ExecuteTest(Base):
    def test_success_end_to_end(self):
        self.spool()
        summary, renames = self.execute()
        self.assertEqual((summary["result"], summary["verdict"], summary["session"]), ("ok", "sufficient", "[PR3 - T #1]"))
        self.assertTrue(summary["comment"].endswith("issuecomment-9"))
        self.assertEqual(summary["rename"], "renamed")
        # 보고서 경로를 출력에 넣으면 Hermes가 파일 첨부로 오해한다
        self.assertEqual(summary["report"], "saved")
        self.assertNotIn("/", run.format_summary(dict(summary, comment="skipped")))
        self.assertEqual(renames[0][1:], ["sessions", "rename", "sess_1", "[PR3 - T #1]"])
        posted = [p for path, p in FakeApp.log if path == "/api/comment"][0]
        self.assertEqual(posted["deliveryId"], "d-1")
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
        posted = [p for path, p in FakeApp.log if path == "/api/comment"][0]
        self.assertEqual(posted["deliveryId"], "d-1-failed")
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
        self.assertFalse([1 for path, _ in FakeApp.log if path == "/api/comment"])

    def test_invalid_request_never_calls_github_or_claude(self):
        summary, _ = self.execute("nothing")
        self.assertEqual(summary["result"], "failed")
        self.assertEqual(FakeApp.log, [])

    def test_summary_line_is_fixed_format_and_clean(self):
        line = run.format_summary({"result": "failed", "verdict": "-", "mode": "-", "session": "-", "report": "-",
                                   "comment": "skipped", "rename": "skipped", "error": "나쁜\n줄바꿈 `rm -rf` $(x) <b>"})
        self.assertNotIn("\n", line)
        for ch in "`$<>":
            self.assertNotIn(ch, line)
        self.assertTrue(line.startswith("result=failed"))


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


class SessionAndCleanupTest(Base):
    def test_session_id_from_env_and_db(self):
        self.assertEqual(run.find_session_id(self.home, "github-app", "d-1", {"HERMES_SESSION_ID": "s1"}), "s1")
        self.assertIsNone(run.find_session_id(self.home, "github-app", "d-1", {"HERMES_SESSION_ID": "bad id;"}))
        conn = sqlite3.connect(self.home / "state.db")
        conn.execute("create table sessions (id text, chat_id text, started_at real)")
        conn.execute("insert into sessions values ('old', 'webhook:github-app:d-1', 1)")
        conn.execute("insert into sessions values ('new', 'webhook:github-app:d-1', 2)")
        conn.commit()
        conn.close()
        self.assertEqual(run.find_session_id(self.home, "github-app", "d-1", {}), "new")
        self.assertIsNone(run.find_session_id(self.home, "github-app", "other", {}))

    def test_rename_outcomes(self):
        ok = lambda cmd, **k: subprocess.CompletedProcess(cmd, 0)
        bad = lambda cmd, **k: subprocess.CompletedProcess(cmd, 1)
        env = {"HERMES_SESSION_ID": "s1"}
        self.assertEqual(run.rename_session(self.home, "r", "d", "[PR1]", "/bin/true", env, ok), "renamed")
        self.assertEqual(run.rename_session(self.home, "r", "d", "[PR1]", "/bin/true", env, bad), "failed")
        self.assertEqual(run.rename_session(self.home, "r", "d", "[PR1]", "/nonexistent/hermes", env, ok), "skipped:no_hermes_binary")
        self.assertEqual(run.rename_session(self.home, "r", "d", "[PR1]", "/bin/true", {}, ok), "skipped:no_session")

    def test_cleanup_removes_only_old_files(self):
        for sub in ("requests", "reports"):
            folder = self.home / "testgate" / sub
            folder.mkdir(parents=True)
            old, fresh = folder / "old.json", folder / "fresh.json"
            old.write_text("{}")
            fresh.write_text("{}")
            past = time.time() - 40 * 86400
            os.utime(old, (past, past))
        run.cleanup(self.home, 30)
        for sub in ("requests", "reports"):
            self.assertFalse((self.home / "testgate" / sub / "old.json").exists())
            self.assertTrue((self.home / "testgate" / sub / "fresh.json").exists())


class FilterSpoolTest(unittest.TestCase):
    PAYLOAD = {"deliveryId": "e69-1", "event": {
        "kind": "comment", "action": "created", "target": "pull_request", "number": 7, "commentId": 1, "url": "u",
        "repo": {"owner": "alice", "name": "r", "fullName": "alice/r"}, "author": {"login": "alice", "type": "User"},
        "body": "/qa [abc1234] 비밀 서술\n둘째 줄"}}

    def run_filter(self, payload, extra_env=None):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        cfg = pathlib.Path(tmp.name) / "testgate.json"
        cfg.write_text(json.dumps({"allowed_authors": ["alice"], "allowed_repo_owners": ["alice"]}))
        env = dict(os.environ, TESTGATE_CONFIG=str(cfg))
        env.pop("TESTGATE_NO_SPOOL", None)
        env.update(extra_env or {})
        proc = subprocess.run([sys.executable, str(ROOT / "scripts" / "qa_filter.py")], input=json.dumps(payload),
                              capture_output=True, text=True, env=env)
        return proc, pathlib.Path(tmp.name)

    def test_spools_request_and_hides_text_from_output(self):
        proc, home = self.run_filter(self.PAYLOAD)
        self.assertEqual(proc.returncode, 0)
        out = json.loads(proc.stdout)
        self.assertEqual(out["qa"]["commit"], "abc1234")
        self.assertNotIn("비밀 서술", proc.stdout)
        self.assertGreater(out["qa"]["text_chars"], 0)
        spooled = home / "testgate" / "requests" / "e69-1.json"
        self.assertEqual(stat.S_IMODE(spooled.stat().st_mode), 0o600)
        data = json.loads(spooled.read_text(encoding="utf-8"))
        self.assertEqual((data["repo"], data["pr"], data["commit"]), ("alice/r", 7, "abc1234"))
        self.assertEqual(data["text"], "비밀 서술\n둘째 줄")

    def test_existing_request_is_not_overwritten(self):
        proc, home = self.run_filter(self.PAYLOAD)
        first = (home / "testgate" / "requests" / "e69-1.json").read_text()
        payload = json.loads(json.dumps(self.PAYLOAD))
        payload["event"]["body"] = "/qa 다른 서술"
        cfg = home / "testgate.json"
        env = dict(os.environ, TESTGATE_CONFIG=str(cfg))
        env.pop("TESTGATE_NO_SPOOL", None)
        subprocess.run([sys.executable, str(ROOT / "scripts" / "qa_filter.py")], input=json.dumps(payload), capture_output=True, text=True, env=env)
        self.assertEqual((home / "testgate" / "requests" / "e69-1.json").read_text(), first)

    def test_bad_delivery_id_fails_closed(self):
        payload = json.loads(json.dumps(self.PAYLOAD))
        payload["deliveryId"] = "../evil"
        proc, home = self.run_filter(payload)
        self.assertEqual(proc.returncode, 1)
        self.assertEqual(proc.stdout, "")
        self.assertFalse((home / "testgate").exists())

    def test_no_spool_mode_prints_full_result(self):
        proc, home = self.run_filter(self.PAYLOAD, {"TESTGATE_NO_SPOOL": "1"})
        self.assertIn("비밀 서술", proc.stdout)
        self.assertFalse((home / "testgate").exists())

    def test_discarded_requests_write_nothing(self):
        payload = json.loads(json.dumps(self.PAYLOAD))
        payload["event"]["body"] = "그냥 코멘트"
        proc, home = self.run_filter(payload)
        self.assertEqual(proc.stdout, "")
        self.assertFalse((home / "testgate").exists())


if __name__ == "__main__":
    unittest.main()
