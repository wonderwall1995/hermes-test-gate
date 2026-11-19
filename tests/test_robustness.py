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
        summary, _ = self.guide("issue")
        self.assertEqual((summary["result"], summary["mode"], summary["session"]), ("ok", "guide", "[이슈3 - 안내]"))
        paths = [path for path, _ in FakeApp.log]
        self.assertEqual(paths, ["/api/comment"], "PR 조회 없이 코멘트만 게시한다")
        body = FakeApp.log[0][1]["body"]
        self.assertIn("이슈 코멘트의 `/qa`는 지원하지 않습니다", body)
        self.assertTrue(body.rstrip().endswith("세션: `[이슈3 - 안내]`"))
        self.assertEqual(FakeApp.log[0][1]["deliveryId"], "d-1")
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
        for bad in ("commit", "x", 1, True):
            self.spool("d-bad", target=bad)
            with self.assertRaises(run.RunError, msg=repr(bad)):
                run.load_request(self.request_path("d-bad"), ["alice"])

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

    def call_main(self):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = run.main(str(pathlib.Path(self.tmp.name) / "none.json"), None)
        return code, out.getvalue()

    def test_uncaught_failure_returns_1_with_a_summary_and_a_log(self):
        original = run.execute
        run.execute = lambda *a, **k: (_ for _ in ()).throw(KeyError("뜻밖"))
        self.addCleanup(lambda: setattr(run, "execute", original))
        with self.assertLogs("testgate", "ERROR") as logs:
            code, out = self.call_main()
        self.assertEqual(code, 1)
        self.assertEqual(json.loads(out.strip().splitlines()[-1]), {"version": 1, "status": "failed", "session_name": None})
        self.assertTrue(any("예상 밖 오류로 중단" in line for line in logs.output))

    def test_missing_secret_is_reported_and_logged(self):
        os.environ.pop("TESTGATE_GITHUB_APP_SECRET")
        with self.assertLogs("testgate", "ERROR") as logs:
            code, out = self.call_main()
        self.assertEqual(code, 1)
        self.assertNotIn("TESTGATE_GITHUB_APP_SECRET", out, "결과 줄에는 약속된 값만 나간다")
        self.assertTrue(any("TESTGATE_GITHUB_APP_SECRET" in line for line in logs.output))


class LauncherLogTest(unittest.TestCase):
    """bin/testgate-run 이 결과 한 줄만 표준 출력에 내고, 기록은 로그 파일로 보내는지 시험한다."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.home = pathlib.Path(self.tmp.name)
        self.env = {k: v for k, v in os.environ.items() if not k.startswith("TESTGATE_")}
        self.env["HERMES_HOME"] = str(self.home)
        self.env["TESTGATE_CONFIG"] = str(self.home / "none.json")
        self.launcher = ROOT / "bin" / "testgate-run"

    def launch(self):
        return subprocess.run([str(self.launcher), "--request", str(self.home / "r.json"), "--context", ""],
                              env=self.env, cwd=str(self.home), capture_output=True, text=True, timeout=30)

    def test_stdout_is_only_the_result_and_logs_go_to_the_file(self):
        proc = self.launch()
        self.assertEqual(proc.returncode, 1, "비밀이 없어서 1로 끝나야 한다")
        self.assertEqual(json.loads(proc.stdout), {"version": 1, "status": "failed", "session_name": None})
        self.assertEqual(proc.stderr, "")
        log = (self.home / "logs" / "testgate.log").read_text(encoding="utf-8")
        self.assertIn("TESTGATE_GITHUB_APP_SECRET", log)
        self.assertRegex(log, r"\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}")
        import stat
        self.assertEqual(stat.S_IMODE((self.home / "logs" / "testgate.log").stat().st_mode), 0o600)

    def test_large_log_is_rotated_once(self):
        logs = self.home / "logs"
        logs.mkdir()
        (logs / "testgate.log").write_text("x" * 1_100_000)
        self.launch()
        self.assertTrue((logs / "testgate.log.1").exists())
        self.assertLess((logs / "testgate.log").stat().st_size, 5000)

    def test_unwritable_log_location_does_not_stop_the_command(self):
        (self.home / "logs").write_text("폴더가 아니라 파일")
        proc = self.launch()
        self.assertEqual(proc.returncode, 1)
        self.assertEqual(json.loads(proc.stdout)["status"], "failed")


if __name__ == "__main__":
    unittest.main()
