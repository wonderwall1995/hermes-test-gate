"""확인 코멘트 -> 수정 -> 멘션 흐름을 시험한다. (2026-11-09 계획의 단계 A)"""

import json
import os
import pathlib
import sys
import tempfile
import unittest

from testgate import config, githubapp, run
from tests import test_run
from tests.test_run import Base, FakeApp, final_comments

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / "scripts"))
import qa_filter  # noqa: E402

GOOD_OUTPUT = {"mode": "evaluate", "summary": "요약", "notes": "", "changes": [
    {"path": "a.py", "change_summary": "c", "tested": "no", "evidence_quote": "", "request": "r", "scenarios": []}]}


class AckFlowTest(Base):
    def setUp(self):
        super().setUp()
        os.environ["FAKE_OUTPUT"] = json.dumps(GOOD_OUTPUT)

    def calls_in_order(self):
        return [path for path, _ in FakeApp.log if path.startswith("/api/comment")]

    def test_ack_is_posted_before_the_pr_is_fetched(self):
        self.spool(author="alice")
        self.execute()
        order = [path for path, _ in FakeApp.log]
        self.assertEqual(order[0], "/api/comment")
        self.assertLess(order.index("/api/comment"), order.index("/api/pr"))
        self.assertEqual(self.calls_in_order(), ["/api/comment", "/api/comment/update"])
        ack = FakeApp.log[0][1]
        self.assertEqual(ack["deliveryId"], "d-1-ack")
        self.assertIn("세션: `[PR3 #1]`", ack["body"])

    def test_result_replaces_the_ack_and_mentions_the_requester(self):
        self.spool(author="alice")
        summary, _ = self.execute()
        update = final_comments()[0]
        self.assertEqual(update["commentId"], 9)
        self.assertTrue(update["body"].startswith("@alice\n\n# QA 테스트 평가 보고서"))
        self.assertTrue(summary["comment"].endswith("issuecomment-9"))

    def test_report_file_has_no_mention_prefix(self):
        self.spool(author="alice")
        self.execute()
        saved = (self.home / "testgate" / "reports" / "d-1.md").read_text(encoding="utf-8")
        self.assertTrue(saved.startswith("# QA 테스트 평가 보고서"))

    def test_mention_can_be_turned_off(self):
        self.spool(author="alice")
        self.settings["mention_requester"] = False
        self.execute()
        self.assertNotIn("@alice", final_comments()[0]["body"])

    def test_invalid_author_is_never_mentioned(self):
        for bad in ("a b", "-x", "x" * 40, "a\n@evil", "", None, 5, "alice]("):
            FakeApp.log.clear()
            self.spool(author=bad)
            self.execute()
            body = final_comments()[0]["body"]
            self.assertTrue(body.startswith("# QA"), repr(bad))

    def test_failure_also_edits_the_ack_and_mentions(self):
        self.spool(author="alice")
        os.environ["FAKE_MODE"] = "fail"
        summary, _ = self.execute()
        self.assertEqual(summary["result"], "failed")
        update = final_comments()[0]
        self.assertEqual(update["commentId"], 9)
        self.assertTrue(update["body"].startswith("@alice\n\n분석에 실패했습니다"))

    def test_update_failure_falls_back_to_a_new_comment_and_fixes_the_ack(self):
        self.spool(author="alice")
        FakeApp.behavior["update_status"] = 502
        with self.assertLogs("testgate", "ERROR"):
            summary, _ = self.execute()
        self.assertEqual(summary["result"], "ok")
        posts = [p for path, p in FakeApp.log if path == "/api/comment"]
        self.assertEqual([p["deliveryId"] for p in posts], ["d-1-ack", "d-1"])
        self.assertTrue(posts[1]["body"].startswith("@alice\n\n# QA"))
        self.assertTrue(summary["comment"].endswith("issuecomment-9"))

    def test_ack_failure_posts_the_result_as_a_plain_comment(self):
        self.spool(author="alice")
        original = self.app.post_comment_ref
        calls = []
        def flaky(repo, pr, body, delivery_id):
            calls.append(delivery_id)
            if delivery_id.endswith("-ack"):
                raise githubapp.GithubAppError("down")
            return original(repo, pr, body, delivery_id)
        self.app.post_comment_ref = flaky
        with self.assertLogs("testgate", "ERROR"):
            summary, _ = self.execute()
        self.assertEqual(summary["result"], "ok")
        self.assertNotIn("/api/comment/update", [path for path, _ in FakeApp.log])
        self.assertEqual([p["deliveryId"] for path, p in FakeApp.log if path == "/api/comment"], ["d-1"])

    def test_old_github_app_without_comment_id_still_delivers_the_result(self):
        self.spool(author="alice")
        original = self.app._post
        def old(path, payload):
            data = original(path, payload)
            data.pop("commentId", None)
            return data
        self.app._post = old
        summary, _ = self.execute()
        self.assertEqual(summary["result"], "ok")
        posts = [p for path, p in FakeApp.log if path == "/api/comment"]
        self.assertEqual([p["deliveryId"] for p in posts], ["d-1-ack", "d-1"], "id가 없으면 수정하지 않고 새 코멘트로 올린다")

    def test_optional_extra_notification_comment(self):
        self.spool(author="alice")
        self.settings["notify_with_new_comment"] = True
        self.execute()
        posts = [p for path, p in FakeApp.log if path == "/api/comment"]
        self.assertEqual([p["deliveryId"] for p in posts], ["d-1-ack", "d-1-notify"])
        self.assertTrue(posts[1]["body"].startswith("@alice 결과가 준비되었습니다: https://"))

    def test_no_extra_notification_by_default(self):
        self.spool(author="alice")
        self.execute()
        self.assertEqual(self.calls_in_order(), ["/api/comment", "/api/comment/update"])

    def test_post_comments_off_posts_nothing(self):
        self.spool(author="alice")
        self.settings["post_comments"] = False
        self.execute()
        self.assertEqual(self.calls_in_order(), [])

    def test_guidance_for_unsupported_locations_has_no_ack(self):
        self.spool(author="alice", unsupported="issue", text="")
        self.execute()
        self.assertEqual(self.calls_in_order(), ["/api/comment"])
        self.assertEqual(FakeApp.log[0][1]["deliveryId"], "d-1")


class AckSupportTest(unittest.TestCase):
    def test_filter_stores_the_author_login(self):
        with tempfile.TemporaryDirectory() as tmp:
            os.environ["TESTGATE_CONFIG"] = str(pathlib.Path(tmp) / "testgate.json")
            os.environ["HERMES_HOME"] = tmp
            self.addCleanup(os.environ.pop, "TESTGATE_CONFIG", None)
            self.addCleanup(os.environ.pop, "HERMES_HOME", None)
            payload = {"deliveryId": "d9", "event": {"repo": {"fullName": "alice/r"}, "number": 3,
                                                    "author": {"login": "alice", "type": "User"}}}
            parsed = {"commit": None, "text": "x", "truncated": False, "free": False}
            self.assertTrue(qa_filter.write_request(payload, parsed))
            data = json.loads((pathlib.Path(tmp) / "testgate" / "requests" / "d9.json").read_text())
            self.assertEqual(data["author"], "alice")

    def test_notify_settings_must_be_booleans(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = pathlib.Path(tmp) / "testgate.json"
            path.write_text(json.dumps({"analysis": {"mention_requester": "no", "notify_with_new_comment": 1}}))
            settings = config.load_analysis_config(path)
        self.assertEqual((settings["mention_requester"], settings["notify_with_new_comment"]), (True, False))


if __name__ == "__main__":
    unittest.main()


class UsageLogTest(Base):
    def test_usage_is_logged_when_present(self):
        from testgate import runner
        self.assertEqual(runner._usage({"input_tokens": 5, "output_tokens": 7, "service_tier": "x", "cache_read_input_tokens": True}),
                         {"input_tokens": 5, "output_tokens": 7})
        self.assertEqual(runner._usage(None), {})
        self.assertEqual(runner._usage("nope"), {})


class ConfigLocationTest(unittest.TestCase):
    """설정 파일은 저장소 안에 있고, 설치된 코드는 안내 파일(config.path)로 그 위치를 찾는다."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.home = pathlib.Path(self.tmp.name) / "home"
        self.repo = pathlib.Path(self.tmp.name) / "repo"
        (self.home / "testgate").mkdir(parents=True)
        self.repo.mkdir()
        self.saved = {k: os.environ.get(k) for k in ("HERMES_HOME", "TESTGATE_CONFIG")}
        os.environ.pop("TESTGATE_CONFIG", None)
        os.environ["HERMES_HOME"] = str(self.home)
        self.addCleanup(self.restore)

    def restore(self):
        for k, v in self.saved.items():
            os.environ.pop(k, None) if v is None else os.environ.__setitem__(k, v)

    def point(self, target):
        (self.home / "testgate" / "config.path").write_text(f"{target}\n\n# [hermes-test-gate] 생성한 파일입니다.\n", encoding="utf-8")

    def test_pointer_file_is_followed_by_both_readers(self):
        target = self.repo / "testgate.json"
        self.point(target)
        self.assertEqual(config.config_path(), target)
        self.assertEqual(qa_filter.config_path(), target)

    def test_legacy_location_is_the_fallback_without_a_pointer(self):
        self.assertEqual(config.config_path(), self.home / "testgate.json")
        self.assertEqual(qa_filter.config_path(), self.home / "testgate.json")

    def test_environment_variable_wins_over_the_pointer(self):
        self.point(self.repo / "testgate.json")
        os.environ["TESTGATE_CONFIG"] = "/x/y.json"
        self.assertEqual(str(config.config_path()), "/x/y.json")
        self.assertEqual(str(qa_filter.config_path()), "/x/y.json")

    def test_relative_or_comment_only_pointer_is_ignored(self):
        (self.home / "testgate" / "config.path").write_text("relative/path.json\n# 주석\n", encoding="utf-8")
        self.assertEqual(config.config_path(), self.home / "testgate.json")
        (self.home / "testgate" / "config.path").write_text("# 주석만 있음\n", encoding="utf-8")
        self.assertEqual(qa_filter.config_path(), self.home / "testgate.json")

    def test_requests_and_launcher_live_under_the_home_not_next_to_the_config(self):
        self.point(self.repo / "testgate.json")
        self.assertEqual(qa_filter.spool_dir(), self.home / "testgate" / "requests")
        self.assertEqual(qa_filter.launcher_path(), self.home / "testgate" / "testgate-run")

    def test_filter_reads_accounts_from_the_repo_file(self):
        (self.repo / "testgate.json").write_text(json.dumps({"allowed_authors": ["bob"], "allowed_repo_owners": ["bob"]}))
        self.point(self.repo / "testgate.json")
        self.assertEqual(qa_filter.load_config(), {"allowed_authors": ["bob"], "allowed_repo_owners": ["bob"]})
        self.assertEqual(config.load_allowed_owners(), ["bob"])


class HtmlFileTest(Base):
    def test_html_report_is_saved_next_to_the_markdown_with_private_permissions(self):
        import stat
        self.spool(author="alice")
        os.environ["FAKE_OUTPUT"] = json.dumps(GOOD_OUTPUT)
        self.execute()
        folder = self.home / "testgate" / "reports"
        html_file = folder / "d-1.html"
        self.assertTrue(html_file.exists())
        self.assertEqual(stat.S_IMODE(html_file.stat().st_mode), 0o600)
        text = html_file.read_text(encoding="utf-8")
        self.assertTrue(text.startswith("<!doctype html>"))
        self.assertNotIn("<script", text)


class ReportLinkTest(Base):
    def setUp(self):
        super().setUp()
        os.environ["FAKE_OUTPUT"] = json.dumps(GOOD_OUTPUT)

    def uploads(self):
        return [p for path, p in FakeApp.log if path == "/api/report"]

    def test_off_by_default_nothing_is_uploaded(self):
        self.spool(author="alice")
        self.execute()
        self.assertEqual(self.uploads(), [])
        self.assertNotIn("HTML 보고서", final_comments()[0]["body"])

    def test_link_is_added_before_the_session_line_and_html_is_uploaded(self):
        self.spool(author="alice")
        self.settings["upload_report"] = True
        self.execute()
        up = self.uploads()
        self.assertEqual(len(up), 1)
        self.assertTrue(up[0]["html"].startswith("<!doctype html>"))
        self.assertEqual(up[0]["deliveryId"], "d-1")
        body = final_comments()[0]["body"]
        link = "[HTML 보고서 받기](https://w.example.dev/r/" + "A" * 43 + ")"
        self.assertIn("\n# HTML 보고서\n\n" + link, body)
        self.assertGreater(body.index("# HTML 보고서"), body.index("세션:"), "맨 아래에 둔다")
        self.assertTrue(body.rstrip().endswith("(HTML 파일, 7일간 받을 수 있음)"))
        saved = (self.home / "testgate" / "reports" / "d-1.md").read_text(encoding="utf-8")
        self.assertEqual(saved, body.split("\n", 2)[2] if body.startswith("@alice") else body)

    def test_upload_failure_still_posts_the_result_without_a_link(self):
        self.spool(author="alice")
        self.settings["upload_report"] = True
        FakeApp.behavior["report_status"] = 502
        with self.assertLogs("testgate", "ERROR"):
            summary, _ = self.execute()
        self.assertEqual(summary["result"], "ok")
        self.assertNotIn("HTML 보고서", final_comments()[0]["body"])

    def test_returned_address_must_look_like_a_report_link(self):
        for bad in ("http://x.example/r/" + "A" * 43, "https://x.example/r/short", "https://x.example/other/" + "A" * 43,
                    "https://x.example/r/" + "A" * 43 + ")[evil](http://e", "javascript:alert(1)"):
            original = self.app._post
            self.app._post = lambda path, payload, b=bad: {"ok": True, "url": b} if path == "/api/report" else original(path, payload)
            with self.assertRaises(githubapp.GithubAppError):
                self.app.upload_report("alice/r", 3, "<p>x</p>", "d-1")
            self.app._post = original

    def test_free_answers_are_never_uploaded(self):
        self.spool(author="alice", free=True, text="질문")
        self.settings["upload_report"] = True
        os.environ["FAKE_OUTPUT"] = json.dumps({"answer": "답"})
        self.execute()
        self.assertEqual(self.uploads(), [])

    def test_setting_must_be_boolean(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = pathlib.Path(tmp) / "testgate.json"
            path.write_text(json.dumps({"analysis": {"upload_report": "yes"}}))
            self.assertFalse(config.load_analysis_config(path)["upload_report"])
