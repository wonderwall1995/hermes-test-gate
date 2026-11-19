"""해설 파일(contextfile.py) 시험.

해설 파일을 만든 프로그램은 필요 없다. 파일의 약속만 지키면 되므로 시험은 손으로 만든 파일로 한다.
"""

import json
import os
import pathlib
import stat
import tempfile
import unittest

from testgate import analyze, contextfile, knowledge
from testgate.contextfile import ContextFileError, ContextFileKnowledge, read_file
from tests.test_run import Base, final_comments
from tests.test_runner_analyze import CONTEXT, REQUEST, FakeClaudeCase

DOC = {"id": "ced:amount", "title": "CED 해설: amount", "text": "금액의 뜻"}


class FileCase(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.dir = pathlib.Path(tmp.name)
        self.path = self.dir / "d-1.context.json"

    def write(self, data, raw=None):
        self.path.write_text(raw if raw is not None else json.dumps(data), encoding="utf-8")

    def reason(self, data=None, raw=None):
        if data is not None or raw is not None:
            self.write(data, raw)
        with self.assertRaises(ContextFileError) as ctx:
            read_file(self.path)
        return ctx.exception.reason


class ReadFileTest(FileCase):
    def test_no_file_means_nothing_to_do(self):
        self.assertIsNone(read_file(self.path))

    def test_valid_file(self):
        self.write({"version": 1, "docs": [DOC], "notices": ["안내 하나"]})
        self.assertEqual(read_file(self.path), ([DOC], ["안내 하나"]))

    def test_docs_and_notices_may_be_empty_or_missing(self):
        self.write({"version": 1})
        self.assertEqual(read_file(self.path), ([], []))
        self.write({"version": 1, "docs": [], "notices": []})
        self.assertEqual(read_file(self.path), ([], []))

    def test_unknown_fields_are_ignored(self):
        self.write({"version": 1, "docs": [dict(DOC, future="x")], "future_top": [1]})
        self.assertEqual(read_file(self.path)[0], [DOC])

    def test_blank_and_idless_docs_are_skipped(self):
        self.write({"version": 1, "docs": [dict(DOC, text="  "), dict(DOC, id=""), DOC]})
        self.assertEqual(read_file(self.path)[0], [DOC])

    def test_the_file_is_never_modified(self):
        self.write({"version": 1, "docs": [DOC]})
        before = self.path.read_bytes()
        read_file(self.path)
        self.assertEqual(self.path.read_bytes(), before)

    def test_broken_files_give_a_reason_code(self):
        cases = {
            "not json": None, "[]": None, "5": None, "null": None,
            '{"docs": []}': None, '{"version": "1"}': None, '{"version": true}': None, '{"version": 1.0}': None,
            '{"version": 1, "docs": {}}': None, '{"version": 1, "docs": "x"}': None,
            '{"version": 1, "docs": [5]}': None, '{"version": 1, "docs": [{"id": "a", "title": "t"}]}': None,
            '{"version": 1, "docs": [{"id": "a", "title": "t", "text": 5}]}': None,
            '{"version": 1, "notices": "x"}': None, '{"version": 1, "notices": [5]}': None,
        }
        for raw in cases:
            with self.subTest(raw=raw):
                self.assertEqual(self.reason(raw=raw), contextfile.BAD_OUTPUT)

    def test_invalid_utf8(self):
        self.path.write_bytes(b"\xff\xfe\x00")
        self.assertEqual(self.reason(), contextfile.BAD_OUTPUT)

    def test_other_version_is_refused(self):
        self.assertEqual(self.reason({"version": 2, "docs": [DOC]}), contextfile.UNSUPPORTED_VERSION)

    def test_too_large(self):
        self.path.write_bytes(b" " * (contextfile.MAX_FILE_BYTES + 1))
        self.assertEqual(self.reason(), contextfile.TOO_LARGE)

    def test_a_symlink_is_not_followed(self):
        outside = self.dir / "outside.json"
        outside.write_text(json.dumps({"version": 1, "docs": [DOC]}))
        os.symlink(outside, self.path)
        self.assertEqual(self.reason(), contextfile.UNREADABLE)

    def test_a_directory_or_fifo_is_not_read_and_does_not_hang(self):
        self.path.mkdir()
        self.assertEqual(self.reason(), contextfile.UNREADABLE)
        self.path.rmdir()
        os.mkfifo(self.path)
        self.assertEqual(self.reason(), contextfile.UNREADABLE)  # 멈추면 이 시험이 끝나지 않는다

    def test_docs_and_notices_are_limited_in_number_and_length(self):
        many = [dict(DOC, id=f"d{i}") for i in range(contextfile.MAX_DOCS + 10)]
        notices = [f"안내 {i}" for i in range(contextfile.MAX_NOTICES + 3)]
        self.write({"version": 1, "docs": many, "notices": notices[:-1] + ["가" * 1000]})
        docs, got = read_file(self.path)
        self.assertEqual(len(docs), contextfile.MAX_DOCS)
        self.assertEqual(len(got), contextfile.MAX_NOTICES)
        self.write({"version": 1, "notices": ["가" * 1000]})
        self.assertEqual(len(read_file(self.path)[1][0]), contextfile.MAX_NOTICE_CHARS)

    def test_notices_become_single_lines_and_urls_stop_being_links(self):
        self.write({"version": 1, "notices": ["첫 줄\n둘째 줄  끝", "클릭http://evil.test/x", "www.evil.test"]})
        _, notices = read_file(self.path)
        self.assertEqual(notices[0], "첫 줄 둘째 줄 끝")
        for n in notices:
            self.assertNotIn("://", n)
            self.assertNotIn("www.", n.lower())

    def test_error_reason_never_contains_the_file_content_or_path(self):
        self.write(None, raw='{"version": 1, "docs": [{"id": "비밀 내용"}]}')
        with self.assertRaises(ContextFileError) as ctx:
            read_file(self.path)
        self.assertNotIn("비밀", str(ctx.exception))
        self.assertNotIn(str(self.dir), str(ctx.exception))


class KnowledgeTest(FileCase):
    def kb(self, **kw):
        return ContextFileKnowledge(self.path, **kw)

    def test_no_file_no_documents_and_no_notes(self):
        kb = self.kb()
        self.assertEqual(kb.load(CONTEXT), [])
        self.assertEqual(kb.drain_notes(), [])

    def test_documents_and_a_generic_note(self):
        self.write({"version": 1, "docs": [DOC], "notices": ["안내 하나"]})
        kb = self.kb()
        self.assertEqual(kb.load(CONTEXT), [DOC])
        self.assertEqual(kb.drain_notes(), ["참고 문서 1건이 첨부됨: CED 해설: amount", "안내 하나"])

    def test_notes_are_drained_once(self):
        self.write({"version": 1, "docs": [DOC]})
        kb = self.kb()
        kb.load(CONTEXT)
        self.assertTrue(kb.drain_notes())
        self.assertEqual(kb.drain_notes(), [])

    def test_only_five_titles_are_named(self):
        docs = [dict(DOC, id=f"d{i}", title=f"제목{i}") for i in range(8)]
        self.write({"version": 1, "docs": docs})
        kb = self.kb()
        kb.load(CONTEXT)
        (note,) = kb.drain_notes()
        self.assertEqual(note, "참고 문서 8건이 첨부됨: 제목0, 제목1, 제목2, 제목3, 제목4 외 3건")

    def test_a_notice_only_file_adds_a_note_and_no_documents(self):
        self.write({"version": 1, "docs": [], "notices": ["참고 문서 공급자가 응답하지 않아 해설 없이 분석함 (timeout)."]})
        kb = self.kb()
        self.assertEqual(kb.load(CONTEXT), [])
        self.assertEqual(kb.drain_notes(), ["참고 문서 공급자가 응답하지 않아 해설 없이 분석함 (timeout)."])

    def test_size_limits_cut_documents_and_say_so(self):
        self.write({"version": 1, "docs": [dict(DOC, id="a", text="가" * 100), dict(DOC, id="b", text="나" * 100)]})
        kb = self.kb(max_doc_chars=50, max_total_chars=60)
        docs = kb.load(CONTEXT)
        self.assertEqual([len(d["text"]) for d in docs], [50])
        self.assertTrue(any("1건은 크기 한도로 뺐습니다" in n for n in kb.drain_notes()))

    def test_a_broken_file_gives_a_reason_and_no_documents(self):
        self.write(None, raw="{")
        kb = self.kb()
        self.assertEqual(kb.load(CONTEXT), [])
        self.assertEqual(kb.drain_notes(), ["참고 문서 파일을 읽지 못해 해설 없이 분석함 (bad_output)."])

    def test_titles_are_cleaned_for_the_report(self):
        self.write({"version": 1, "docs": [dict(DOC, title="링크http://evil.test  제목\n끝")]})
        kb = self.kb()
        kb.load(CONTEXT)
        (note,) = kb.drain_notes()
        self.assertNotIn("://", note)
        self.assertNotIn("\n", note)

    def test_the_text_of_a_document_is_passed_through_unchanged(self):
        self.write({"version": 1, "docs": [dict(DOC, text="# 제목\n\n> 인용\n본문")]})
        self.assertEqual(self.kb().load(CONTEXT)[0]["text"], "# 제목\n\n> 인용\n본문")


class CompositeTest(FileCase):
    def test_directory_documents_come_first_and_notes_are_gathered(self):
        docs_dir = self.dir / "docs"
        docs_dir.mkdir()
        (docs_dir / "note.md").write_text("폴더 문서", encoding="utf-8")
        self.write({"version": 1, "docs": [DOC]})
        kb = knowledge.CompositeKnowledge([knowledge.DirectoryKnowledge([str(docs_dir)]), ContextFileKnowledge(self.path)])
        self.assertEqual([d["id"] for d in kb.load(CONTEXT)], ["note.md", "ced:amount"])
        self.assertEqual(len(kb.drain_notes()), 1)

    def test_sources_without_notes_are_fine(self):
        kb = knowledge.CompositeKnowledge([knowledge.NullKnowledge(), ContextFileKnowledge(self.path)])
        self.assertEqual(kb.load(CONTEXT), [])
        self.assertEqual(kb.drain_notes(), [])


class AnalyzeTest(FakeClaudeCase, FileCase):
    def setUp(self):
        FakeClaudeCase.setUp(self)
        FileCase.setUp(self)

    def kb(self):
        return ContextFileKnowledge(self.path)

    def test_documents_reach_the_prompt_as_untrusted_data_and_the_report_names_them(self):
        self.write({"version": 1, "docs": [DOC]})
        outcome = analyze.analyze(REQUEST, CONTEXT, self.kb(), self.runner())
        prompt_text = json.loads(self.record.read_text())["stdin"]
        self.assertIn("reference:ced:amount", prompt_text)
        self.assertIn("금액의 뜻", prompt_text)
        self.assertIn("참고 문서 1건이 첨부됨: CED 해설: amount", outcome["notes"])
        self.assertIn("## 비고", outcome["markdown"])
        self.assertIn("참고 문서 1건이 첨부됨", outcome["markdown"])

    def test_without_a_file_the_analysis_is_exactly_as_before(self):
        outcome = analyze.analyze(REQUEST, CONTEXT, self.kb(), self.runner())
        self.assertFalse(any("참고 문서" in n for n in outcome["notes"]))
        self.assertNotIn("reference:", json.loads(self.record.read_text())["stdin"])

    def test_a_broken_file_does_not_stop_the_analysis(self):
        self.write(None, raw="{")
        outcome = analyze.analyze(REQUEST, CONTEXT, self.kb(), self.runner())
        self.assertEqual(outcome["mode"], "evaluate")
        self.assertIn("참고 문서 파일을 읽지 못해 해설 없이 분석함 (bad_output).", outcome["notes"])
        self.assertIn("해설 없이 분석함", outcome["markdown"])

    def test_hostile_text_cannot_ping_embed_or_link_in_the_posted_report(self):
        evil = {"id": "e", "title": "@everyone [클릭](http://evil.test) <img src=x>", "text": "본문"}
        self.write({"version": 1, "docs": [evil], "notices": ["@admin 링크http://evil.test"]})
        markdown = analyze.analyze(REQUEST, CONTEXT, self.kb(), self.runner())["markdown"]
        section = markdown[markdown.index("## 비고"):]
        self.assertNotIn("@everyone", section)
        self.assertNotIn("@admin", section)
        self.assertIn("@​everyone", section)
        self.assertNotIn("<img", section)
        self.assertNotIn("](", section)
        self.assertNotIn("://", section)

    def test_free_mode_also_gets_the_documents_and_notes(self):
        self.write({"version": 1, "docs": [DOC]})
        os.environ["FAKE_OUTPUT"] = json.dumps({"answer": "답변", "notes": ""})
        outcome = analyze.analyze_free(REQUEST, CONTEXT, self.kb(), self.runner())
        self.assertIn("reference:ced:amount", json.loads(self.record.read_text())["stdin"])
        self.assertTrue(any("참고 문서 1건이 첨부됨" in n for n in outcome["notes"]))


RECORDING_CLAUDE = """#!/usr/bin/env python3
import json, os, sys
open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "prompt.txt"), "w").write(sys.stdin.read())
print(json.dumps({"is_error": False, "structured_output": json.loads(os.environ["FAKE_OUTPUT"]), "total_cost_usd": 0, "duration_ms": 1, "modelUsage": {"m": {}}}))
"""


class ExecuteTest(Base):
    """실제 래퍼 실행(execute) 안에서 요청 파일 옆의 해설 파일을 읽는지."""

    def setUp(self):
        super().setUp()
        claude = self.home / "claude"
        claude.write_text(RECORDING_CLAUDE)
        claude.chmod(claude.stat().st_mode | stat.S_IEXEC)
        self.requests = self.home / "testgate" / "requests"

    def put_context(self, data=None, raw=None, delivery_id="d-1"):
        self.requests.mkdir(parents=True, exist_ok=True)
        (self.requests / f"{delivery_id}.context.json").write_text(raw if raw is not None else json.dumps(data), encoding="utf-8")

    def prompt(self):
        return (self.home / "prompt.txt").read_text(encoding="utf-8")

    def posted(self):
        return final_comments()[0]["body"]

    def test_the_context_file_next_to_the_request_reaches_the_analysis_and_the_report(self):
        self.spool()
        self.put_context({"version": 1, "docs": [DOC], "notices": ["안내 하나"]})
        summary, _ = self.execute()
        self.assertEqual(summary["result"], "ok")
        self.assertIn("reference:ced:amount", self.prompt())
        self.assertIn("금액의 뜻", self.prompt())
        body = self.posted()
        self.assertIn("참고 문서 1건이 첨부됨: CED 해설: amount", body)
        self.assertIn("안내 하나", body)

    def test_without_a_context_file_nothing_changes(self):
        self.spool()
        summary, _ = self.execute()
        self.assertEqual(summary["result"], "ok")
        self.assertNotIn("reference:", self.prompt())
        self.assertNotIn("참고 문서", self.posted())

    def test_a_broken_context_file_does_not_stop_the_analysis(self):
        self.spool()
        self.put_context(raw="{")
        summary, _ = self.execute()
        self.assertEqual(summary["result"], "ok")
        self.assertIn("참고 문서 파일을 읽지 못해 해설 없이 분석함 (bad_output).", self.posted())

    def test_only_the_file_of_the_same_delivery_id_is_used(self):
        self.spool()
        self.put_context({"version": 1, "docs": [DOC]}, delivery_id="other")
        self.execute()
        self.assertNotIn("reference:", self.prompt())

    def test_a_symlinked_context_file_is_not_followed(self):
        self.spool()
        outside = self.home / "outside.json"
        outside.write_text(json.dumps({"version": 1, "docs": [DOC]}))
        os.symlink(outside, self.requests / "d-1.context.json")
        summary, _ = self.execute()
        self.assertEqual(summary["result"], "ok")
        self.assertNotIn("reference:", self.prompt())
        self.assertIn("(unreadable)", self.posted())

    def test_the_context_file_is_left_in_place_for_the_normal_cleanup(self):
        self.spool()
        self.put_context({"version": 1, "docs": [DOC]})
        self.execute()
        self.assertTrue((self.requests / "d-1.context.json").exists())


if __name__ == "__main__":
    unittest.main()
