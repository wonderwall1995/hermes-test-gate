"""조용한 실패 방지: 예상 밖 예외, 지원하지 않는 위치 안내, 로그 파일."""

import contextlib
import io
import json
import os
import pathlib
import subprocess
import sys
import tempfile
import unittest

from testgate import githubapp, ledger, run
from tests import test_run
from tests.test_run import Base, FakeApp

ROOT = pathlib.Path(__file__).resolve().parent.parent


class Boom:
    """호출되면 안 되거나, 예상 밖 예외를 던지는 Claude 대역."""
    def __init__(self, message="내부 상세 정보"):
        self.message = message
        self.calls = 0

    def run(self, *args, **kwargs):
        self.calls += 1
        raise RuntimeError(self.message)


class UnexpectedErrorTest(Base):
    def test_unexpected_exception_posts_failure_comment_and_records_failure(self):
        self.spool()
        self.claude = Boom("비밀처럼 보이는 내부 상세")
        with self.assertLogs("testgate", "ERROR") as logs:
            summary, _ = self.execute()
        self.assertEqual(summary["result"], "failed")
        # 오류 메시지는 요약과 코멘트에 새지 않고 종류만 남는다. 자세한 내용은 로그에만 있다.
        self.assertEqual(summary["error"], "unexpected:RuntimeError")
        posted = test_run.final_comments()
        self.assertEqual([p["commentId"] for p in posted], [9])
        self.assertIn("분석에 실패했습니다", posted[0]["body"])
        self.assertNotIn("비밀처럼", posted[0]["body"])
        self.assertTrue(any("예상 밖 오류" in line for line in logs.output))
        self.assertTrue(any("비밀처럼 보이는 내부 상세" in line for line in logs.output), "로그에는 자세한 내용이 있어야 한다")
        data = ledger.load(ledger.thread_path(self.home, "alice/r", 3), "alice/r", 3)
        self.assertEqual([e["status"] for e in data["entries"]], ["failed"], "pending 으로 남으면 안 된다")

    def test_report_save_failure_still_delivers_the_result(self):
        self.spool()
        os.environ["FAKE_OUTPUT"] = json.dumps({"mode": "evaluate", "summary": "요약", "notes": "", "changes": [
            {"path": "a.py", "change_summary": "c", "tested": "yes", "evidence_quote": "a.py 를 확인했다",
             "request": "", "scenarios": []}]})
        # reports 가 폴더가 아니라 파일이면 저장이 OSError 로 실패한다
        (self.home / "testgate").mkdir(exist_ok=True)
        (self.home / "testgate" / "reports").write_text("not a dir")
        with self.assertLogs("testgate", "ERROR"):
            summary, _ = self.execute()
        self.assertEqual((summary["result"], summary["report"]), ("ok", "not-saved"))
        self.assertTrue(summary["comment"].endswith("issuecomment-9"))

    def test_comment_failure_with_unexpected_error_does_not_crash(self):
        self.spool()
        os.environ["FAKE_OUTPUT"] = json.dumps({"mode": "evaluate", "summary": "요약", "notes": "", "changes": [
            {"path": "a.py", "change_summary": "c", "tested": "no", "evidence_quote": "", "request": "r", "scenarios": []}]})
        def broken(*a, **k):
            raise ValueError("깨진 응답")
        self.app.post_comment = self.app.post_comment_ref = self.app.update_comment = broken
        with self.assertLogs("testgate", "ERROR"):
            summary, _ = self.execute()
        self.assertEqual((summary["result"], summary["comment"], summary["error"]), ("ok", "failed", "unexpected:ValueError"))

    def test_rename_exception_is_contained(self):
        self.spool()
        self.seed_session("d-1")
        os.environ["FAKE_OUTPUT"] = json.dumps({"mode": "evaluate", "summary": "요약", "notes": "", "changes": [
            {"path": "a.py", "change_summary": "c", "tested": "no", "evidence_quote": "", "request": "r", "scenarios": []}]})
        def boom(*a, **k):
            raise ValueError("hermes 호출 실패")
        with self.assertLogs("testgate", "ERROR"):
            summary = run.execute("d-1", self.home, self.settings, ["alice"], self.claude, self.app,
                                  hermes_run=boom, sleep=lambda s: None)
        self.assertEqual((summary["result"], summary["rename"]), ("ok", "failed"))

    def test_cleanup_failure_does_not_stop_the_analysis(self):
        self.spool()
        original = run.cleanup
        run.cleanup = lambda *a, **k: (_ for _ in ()).throw(OSError("정리 실패"))
        self.addCleanup(lambda: setattr(run, "cleanup", original))
        os.environ["FAKE_OUTPUT"] = json.dumps({"mode": "evaluate", "summary": "요약", "notes": "", "changes": [
            {"path": "a.py", "change_summary": "c", "tested": "no", "evidence_quote": "", "request": "r", "scenarios": []}]})
        with self.assertLogs("testgate", "ERROR"):
            summary, _ = self.execute()
        self.assertEqual(summary["result"], "ok")


class UnsupportedLocationTest(Base):
    def guide(self, kind, **settings):
        self.spool("d-1", unsupported=kind, text="", pr=3)
        self.claude = Boom()
        self.settings.update(settings)
        return self.execute()

    def test_issue_comment_gets_guidance_only(self):
        summary, renames = self.guide("issue")
        self.assertEqual((summary["result"], summary["mode"], summary["session"]), ("ok", "guide", "[이슈3 - 안내]"))
        paths = [path for path, _ in FakeApp.log]
        self.assertEqual(paths, ["/api/comment"], "PR 조회 없이 코멘트만 게시한다")
        body = FakeApp.log[0][1]["body"]
        self.assertIn("이슈 코멘트의 `/qa`는 지원하지 않습니다", body)
        self.assertTrue(body.rstrip().endswith("세션: `[이슈3 - 안내]`"))
        self.assertEqual(FakeApp.log[0][1]["deliveryId"], "d-1")
        self.assertEqual(renames[0][-1], "[이슈3 - 안내]")
        self.assertEqual(self.claude.calls, 0)

    def test_review_comment_gets_guidance_with_pr_name(self):
        summary, _ = self.guide("pull_request_review")
        self.assertEqual(summary["session"], "[PR3 - 안내]")
        self.assertIn("대화창(Conversation)에 일반 코멘트로 다시 써", FakeApp.log[0][1]["body"])

    def test_guidance_does_not_touch_the_pr_history(self):
        self.guide("issue")
        self.assertFalse(ledger.thread_path(self.home, "alice/r", 3).exists())

    def test_guidance_respects_post_comments_off(self):
        summary, _ = self.guide("issue", post_comments=False)
        self.assertEqual(summary["comment"], "skipped")
        self.assertEqual(FakeApp.log, [])

    def test_guidance_failure_is_contained(self):
        def broken(*a, **k):
            raise ValueError("깨짐")
        self.app.post_comment = broken
        with self.assertLogs("testgate", "ERROR"):
            summary, _ = self.guide("issue")
        self.assertEqual((summary["result"], summary["comment"]), ("ok", "failed"))

    def test_invalid_unsupported_value_is_rejected(self):
        for bad in ("commit", "pull_request", "x", 1, True):
            self.spool("d-bad", unsupported=bad)
            with self.assertRaises(run.RunError, msg=repr(bad)):
                run.load_request(self.home, "d-bad", ["alice"])

    def test_guidance_still_checks_the_owner(self):
        self.spool("d-1", unsupported="issue", repo="mallory/r")
        summary, _ = self.execute()
        self.assertEqual(summary["result"], "failed")
        self.assertEqual(FakeApp.log, [])


class MainSafetyNetTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.saved = {k: os.environ.get(k) for k in ("HERMES_HOME", "TESTGATE_GITHUB_APP_SECRET", "TESTGATE_CONFIG")}
        os.environ["HERMES_HOME"] = self.tmp.name
        os.environ["TESTGATE_GITHUB_APP_SECRET"] = "s"
        os.environ.pop("TESTGATE_CONFIG", None)
        self.addCleanup(self.restore)
        # basicConfig 는 프로세스 전체에 핸들러를 남겨 다른 시험의 출력을 어지럽힌다. 실제 설정은 LauncherLogTest 가 시험한다.
        original = run._setup_logging
        run._setup_logging = lambda: None
        self.addCleanup(lambda: setattr(run, "_setup_logging", original))

    def restore(self):
        for key, value in self.saved.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value

    def call_main(self, delivery_id="d-1"):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = run.main(delivery_id)
        return code, out.getvalue()

    def test_uncaught_failure_returns_1_with_a_summary_and_a_log(self):
        original = run.execute
        run.execute = lambda *a, **k: (_ for _ in ()).throw(KeyError("뜻밖"))
        self.addCleanup(lambda: setattr(run, "execute", original))
        with self.assertLogs("testgate", "ERROR") as logs:
            code, out = self.call_main()
        self.assertEqual(code, 1)
        self.assertTrue(out.startswith("result=failed"))
        self.assertIn("unexpected:KeyError", out)
        self.assertTrue(any("예상 밖 오류로 중단" in line for line in logs.output))

    def test_missing_secret_is_reported_and_logged(self):
        os.environ.pop("TESTGATE_GITHUB_APP_SECRET")
        with self.assertLogs("testgate", "ERROR") as logs:
            code, out = self.call_main()
        self.assertEqual(code, 1)
        self.assertIn("TESTGATE_GITHUB_APP_SECRET", out)
        self.assertTrue(any("TESTGATE_GITHUB_APP_SECRET" in line for line in logs.output))


class LauncherLogTest(unittest.TestCase):
    """설치된 testgate-run 이 출력과 오류를 로그 파일로 보내는지 시험한다."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.home = pathlib.Path(self.tmp.name)
        self.env = {k: v for k, v in os.environ.items() if not k.startswith("TESTGATE_")}
        self.env["HERMES_HOME"] = str(self.home)
        subprocess.run([str(ROOT / "scripts" / "install.sh")], env=self.env, check=True, capture_output=True)
        self.launcher = self.home / "testgate" / "testgate-run"

    def launch(self, delivery_id="some-id"):
        # 운영에서는 필터가 래퍼 폴더에서 띄운다. 저장소 루트에서 실행하면 설치본이 아니라 저장소의 코드가 불려 온다.
        return subprocess.run([str(self.launcher), delivery_id], env=self.env, cwd=str(self.launcher.parent),
                              capture_output=True, text=True, timeout=30)

    def test_output_and_errors_go_to_the_log_not_the_terminal(self):
        proc = self.launch()
        self.assertEqual((proc.stdout, proc.stderr), ("", ""), "필터가 DEVNULL 로 띄워도 흔적이 로그에 남아야 한다")
        log = (self.home / "logs" / "testgate.log").read_text(encoding="utf-8")
        self.assertIn("시작 id='some-id'", log)
        self.assertIn("TESTGATE_GITHUB_APP_SECRET", log)
        self.assertRegex(log, r"\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}")
        import stat
        self.assertEqual(stat.S_IMODE((self.home / "logs" / "testgate.log").stat().st_mode), 0o600)

    def test_import_errors_are_logged_too(self):
        (self.home / "testgate" / "lib" / "testgate" / "run.py").write_text("raise ImportError('깨진 설치')\n")
        self.launch()
        log = (self.home / "logs" / "testgate.log").read_text(encoding="utf-8")
        self.assertIn("깨진 설치", log)

    def test_large_log_is_rotated_once(self):
        logs = self.home / "logs"
        logs.mkdir()
        (logs / "testgate.log").write_text("x" * 1_100_000)
        self.launch()
        self.assertTrue((logs / "testgate.log.1").exists())
        self.assertLess((logs / "testgate.log").stat().st_size, 5000)

    def test_unwritable_log_location_does_not_stop_the_wrapper(self):
        (self.home / "logs").write_text("폴더가 아니라 파일")
        proc = self.launch()
        self.assertEqual(proc.returncode, 1, "비밀이 없어서 1로 끝나야 한다 (로그 때문에 죽지 않음)")

    def test_hermes_guide_is_installed_with_a_hidden_source_mark(self):
        readme = self.home / "testgate" / "README.md"
        text = readme.read_text(encoding="utf-8")
        self.assertTrue(text.startswith("# TestGate 안내"))
        self.assertTrue(text.rstrip().endswith("-->"))
        self.assertIn("[hermes-test-gate] 현재 Repo(hermes-test-gate)로 생성한 파일입니다", text.rstrip().splitlines()[-1])
        # 원본과 같은 내용에 표시만 덧붙은 것이어야 한다
        source = (ROOT / "docs" / "hermes-guide.md").read_text(encoding="utf-8")
        self.assertTrue(text.startswith(source.rstrip("\n")))

    def test_edited_guide_is_detected_by_check(self):
        (self.home / "testgate" / "README.md").write_text("손으로 고침\n")
        proc = subprocess.run([str(ROOT / "scripts" / "install.sh"), "--check"], env=self.env, capture_output=True, text=True)
        self.assertEqual(proc.returncode, 1)
        self.assertIn("README.md", proc.stderr)

    def test_guide_states_the_facts_hermes_got_wrong(self):
        text = (ROOT / "docs" / "hermes-guide.md").read_text(encoding="utf-8")
        for fact in ("분석에 관여하지 않음", "Claude 구독으로 실행됩니다", "TestGate의 설정입니다",
                     "testgate.log", "TESTGATE_GITHUB_APP_SECRET", "읽거나 출력하거나 대화에 적지 마세요"):
            self.assertIn(fact, text)

    def test_installed_launcher_is_checked(self):
        proc = subprocess.run([str(ROOT / "scripts" / "install.sh"), "--check"], env=self.env, capture_output=True, text=True)
        self.assertEqual(proc.returncode, 0, proc.stderr)


if __name__ == "__main__":
    unittest.main()
