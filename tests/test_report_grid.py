"""카테고리별 아코디언과 번호 붙은 표, HTML 보고서를 시험한다."""

import re
import unittest

from testgate import analyze, htmlreport, report

REQUEST = {"pr": 3, "commit": None}
CONTEXT = {"base_ref": "main"}


def change(path, status="modified", tested="unclear", scenarios=None, coverage="full", reason="", **kw):
    c = {"path": path, "status": status, "change_summary": f"{path} 요약", "tested": tested, "evidence_quote": "",
         "request": "", "scenarios": scenarios if scenarios is not None else [], "coverage": coverage, "reason": reason}
    c.update(kw)
    return c


def scenario(title="제목", steps=("하나", "둘"), expected="기대"):
    return {"title": title, "steps": list(steps), "expected": expected}


def design(changes):
    return {"mode": "design", "summary": "요약", "notes": "", "changes": changes}


class CategoryTest(unittest.TestCase):
    def test_categories_follow_status_and_path(self):
        cases = {
            ("src/a.tsx", "modified"): "modified", ("src/a.tsx", "renamed"): "modified", ("src/a.tsx", "changed"): "modified",
            ("src/b.tsx", "added"): "added", ("src/c.tsx", "removed"): "removed",
            ("db/x.sql", "added"): "docs", ("README.md", "modified"): "docs", ("docs/guide.html", "added"): "docs",
            ("notes.txt", "removed"): "docs", ("MIGRATION.SQL", "modified"): "docs",
        }
        for (path, status), expected in cases.items():
            self.assertEqual(report.categorize({"path": path, "status": status}), expected, (path, status))

    def test_unseen_and_excluded_are_not_in_any_category(self):
        groups = report.by_category([change("a.py"), change("b.py", coverage="unseen", reason="budget"),
                                     change("c.lock", coverage="excluded", reason="generated")])
        self.assertEqual([c["path"] for rows in groups.values() for c in rows], ["a.py"])


class DesignReportTest(unittest.TestCase):
    def render(self, changes, **kw):
        result = design(changes)
        return report.render(REQUEST, CONTEXT, result, "design", [], "[PR3]", **kw)

    def test_each_category_is_an_accordion_with_a_numbered_four_column_grid(self):
        md = self.render([change("a.py", scenarios=[scenario()]), change("n.py", "added", scenarios=[scenario("신규", ("열기",), "열린다")]),
                          change("d.py", "removed", scenarios=[scenario()]), change("q.sql", "added", scenarios=[scenario()])])
        for label in ("수정된 코드 (1)", "추가된 코드 (1)", "삭제된 코드 (1)", "SQL·문서·기타 (1)"):
            self.assertIn(f"<summary><b>{label}</b></summary>", md)
        self.assertEqual(md.count("<details>"), 4)
        self.assertEqual(md.count("</details>"), 4)
        self.assertLess(md.index("수정된 코드"), md.index("추가된 코드"))
        self.assertLess(md.index("추가된 코드"), md.index("삭제된 코드"))
        self.assertLess(md.index("삭제된 코드"), md.index("SQL·문서·기타"))
        self.assertIn("| # | 파일 | 테스트 시도 방법 | 기대 동작 |", md)
        self.assertIn("| 1 | `n.py` | 신규<br>1. 열기 | 열린다 |", md)
        for line in md.splitlines():
            if line.startswith("| ") and not line.startswith("| ---"):
                self.assertEqual(len(re.findall(r"(?<!\\)\|", line)), 5, line)   # 열은 4개로 고정

    def test_blank_line_after_summary_so_github_renders_the_table(self):
        md = self.render([change("a.py", scenarios=[scenario()])])
        self.assertIn("</summary>\n\n| # |", md)
        self.assertIn("|\n\n</details>", md)

    def test_no_character_limit_on_long_cells(self):
        long_step = "가" * 3000
        md = self.render([change("a.py", scenarios=[scenario("긴 제목", (long_step,), "나" * 2000)])])
        self.assertIn(long_step, md)
        self.assertIn("나" * 2000, md)

    def test_numbers_continue_across_scenarios_of_one_file_and_file_name_repeats(self):
        md = self.render([change("a.py", scenarios=[scenario("첫째"), scenario("둘째")])])
        self.assertIn("| 1 | `a.py` | 첫째", md)
        self.assertIn("| 2 | `a.py` | 둘째", md)

    def test_cell_text_cannot_break_the_grid(self):
        md = self.render([change("a.py", scenarios=[scenario("a|b\n<img src=x onerror=1>", ("x | y",), "@bob ![i](u)")])])
        self.assertNotIn("<img", md)
        self.assertIn("a\\|b", md)
        self.assertIn("@​bob", md)
        self.assertNotIn("![", md)

    def test_file_without_scenarios_gets_a_marked_row(self):
        md = self.render([change("a.py")])
        self.assertIn("(제안된 시나리오 없음)", md)

    def test_unseen_and_excluded_have_their_own_lists_not_rows(self):
        md = self.render([change("a.py", scenarios=[scenario()]), change("big.json", coverage="unseen", reason="missing", request="직접 확인"),
                          change("p.lock", coverage="excluded", reason="generated")])
        self.assertIn("## 분석에서 제외한 파일", md)
        self.assertIn("## 확인하지 못한 파일", md)
        grid = md.split("</details>")[0]
        self.assertNotIn("big.json", grid)
        self.assertNotIn("p.lock", grid)

    def test_compact_mode_drops_the_grids_and_keeps_counts(self):
        md = self.render([change("a.py", scenarios=[scenario()]), change("n.py", "added", scenarios=[scenario()])], compact=True)
        self.assertNotIn("<details>", md)
        self.assertIn("수정된 코드: 1개", md)
        self.assertIn("추가된 코드: 1개", md)
        self.assertIn("전체 내용은 서버의 보고서 파일(HTML)에 있습니다", md)


class EvaluateReportTest(unittest.TestCase):
    def test_evaluate_grid_has_state_column_and_numbers(self):
        result = {"mode": "evaluate", "summary": "s", "notes": "", "changes": [
            change("a.py", tested="yes", evidence_quote="a 확인"), change("b.py", "added", tested="no", request="b를 테스트")]}
        md = report.render(REQUEST, CONTEXT, result, "more_tests_needed", [], "[PR3]")
        self.assertIn("| # | 파일 | 변경 요약 | 테스트 | 근거 |", md)
        self.assertIn("| 1 | `a.py` | a.py 요약 | 확인됨 | “a 확인” |", md)
        self.assertIn("<summary><b>추가된 코드 (1)</b></summary>", md)
        self.assertIn("1. `b.py`: b를 테스트", md)


class HtmlReportTest(unittest.TestCase):
    def render(self, changes, mode="design"):
        result = {"mode": mode, "summary": "요약 <b>x</b>", "notes": "", "changes": changes}
        return htmlreport.render_html(REQUEST, CONTEXT, result, "design" if mode == "design" else "sufficient", [], "[PR3 - T #1]")

    def test_structure_and_no_scripts_or_external_resources(self):
        out = self.render([change("a.py", scenarios=[scenario()]), change("n.py", "added", scenarios=[scenario("신규")])])
        self.assertTrue(out.startswith("<!doctype html>"))
        self.assertIn("<details open><summary>수정된 코드 (1)</summary>", out)
        self.assertIn("<details open><summary>추가된 코드 (1)</summary>", out)
        self.assertIn('<td class="num">1</td>', out)
        self.assertNotIn("<script", out)
        self.assertNotIn("http://", out)
        self.assertNotIn("https://", out)
        self.assertIn("default-src 'none'", out)

    def test_every_model_written_string_is_escaped(self):
        evil = '</td><script>alert(1)</script>"><img src=x onerror=alert(1)>'
        out = self.render([change(evil, scenarios=[scenario(evil, (evil,), evil)], change_summary=evil)])
        self.assertNotIn("<script>alert", out)
        self.assertNotIn("<img", out)
        self.assertIn("&lt;script&gt;", out)
        self.assertIn("&lt;b&gt;x&lt;/b&gt;", out)

    def test_evaluate_mode_columns(self):
        out = self.render([change("a.py", tested="yes", evidence_quote="근거")], mode="evaluate")
        self.assertIn("<th>테스트</th>", out)
        self.assertIn("확인됨", out)
        self.assertIn("“근거”", out)

    def test_excluded_unseen_lists_present(self):
        out = self.render([change("p.lock", coverage="excluded", reason="generated"),
                           change("x.json", coverage="unseen", reason="missing", request="직접 확인")])
        self.assertIn("<h2>분석에서 제외한 파일</h2>", out)
        self.assertIn("<h2>확인하지 못한 파일</h2>", out)


class LongCommentTest(unittest.TestCase):
    class Runner:
        def __init__(self, count):
            self.count = count

        def run(self, system, user, schema_):
            changes = [{"path": f"src/f{i:04d}.py", "change_summary": "요약", "tested": "unclear", "evidence_quote": "",
                        "request": "", "scenarios": [{"title": "t" * 200, "steps": ["s" * 300] * 3, "expected": "e" * 200}]}
                       for i in range(self.count)]
            return {"mode": "design", "summary": "요약", "changes": changes, "notes": ""}, {"cost_usd": 0, "duration_ms": 0, "models": []}

    class Knowledge:
        def load(self, context):
            return []

    def context(self, count):
        files = [{"path": f"src/f{i:04d}.py", "status": "modified", "additions": 1, "deletions": 0, "diff_included": True,
                  "coverage": "full", "reason": ""} for i in range(count)]
        diff = "".join(f"diff --git a/{f['path']} b/{f['path']}\n--- a/{f['path']}\n+++ b/{f['path']}\n@@ -1 +1 @@\n+x\n" for f in files)
        return {"title": "T", "body": "", "base_ref": "main", "scope": "pr", "commit": None, "head_sha": "h" * 40, "files": files,
                "diff": diff, "truncated": False}

    def run_it(self, count):
        request = {"deliveryId": "d", "repo": "o/r", "pr": 3, "commit": None, "text": ""}
        return analyze.analyze(request, self.context(count), self.Knowledge(), self.Runner(count))

    def test_short_report_is_posted_in_full(self):
        out = self.run_it(5)
        self.assertIn("<details>", out["markdown"])
        self.assertIn("<!doctype html>", out["html"])

    def test_report_over_the_comment_limit_falls_back_to_counts_but_html_keeps_everything(self):
        out = self.run_it(120)
        self.assertLessEqual(len(out["markdown"]), analyze.MAX_COMMENT_CHARS)
        self.assertNotIn("<details>", out["markdown"])
        self.assertIn("수정된 코드: 120개", out["markdown"])
        self.assertGreater(len(out["html"]), analyze.MAX_COMMENT_CHARS)
        self.assertEqual(out["html"].count('<td class="num">'), 120)


if __name__ == "__main__":
    unittest.main()


class DescriptionClaimsTest(unittest.TestCase):
    DESC = "포트를 7201/7202로 바꿉니다.\n로그인 잠금을 추가합니다."

    def claim(self, quote, status="in_diff", files=("a.py",), check="시도", expected="기대"):
        return {"quote": quote, "status": status, "files": list(files), "check": check, "expected": expected}

    def verify(self, claims, files=("a.py", "b.py")):
        from testgate import schema
        return schema.verify_claims(claims, self.DESC, list(files))

    def test_quote_must_exist_in_the_description(self):
        kept, notes = self.verify([self.claim("포트를 7201/7202로 바꿉니다."), self.claim("지어낸 문장입니다.")])
        self.assertEqual([c["quote"] for c in kept], ["포트를 7201/7202로 바꿉니다."])
        self.assertEqual(len(notes), 1)

    def test_whitespace_differences_are_tolerated_and_quote_is_stored_normalized(self):
        kept, _ = self.verify([self.claim("포트를   7201/7202로\n바꿉니다.")])
        self.assertEqual(kept[0]["quote"], "포트를 7201/7202로 바꿉니다.")

    def test_in_diff_without_a_known_file_is_downgraded(self):
        kept, notes = self.verify([self.claim("포트를 7201/7202로 바꿉니다.", files=("nope.py",))])
        self.assertEqual((kept[0]["status"], kept[0]["files"]), ("unclear", []))
        self.assertTrue(notes)

    def test_unknown_files_are_dropped_but_known_ones_stay(self):
        kept, _ = self.verify([self.claim("포트를 7201/7202로 바꿉니다.", files=("a.py", "x.py", "a.py"))])
        self.assertEqual(kept[0]["files"], ["a.py"])

    def test_not_in_diff_keeps_no_files(self):
        kept, _ = self.verify([self.claim("로그인 잠금을 추가합니다.", "not_in_diff", files=("a.py",))])
        self.assertEqual((kept[0]["status"], kept[0]["files"]), ("not_in_diff", []))

    def test_duplicates_and_empty_description(self):
        kept, _ = self.verify([self.claim("포트를 7201/7202로 바꿉니다."), self.claim("포트를 7201/7202로 바꿉니다.")])
        self.assertEqual(len(kept), 1)
        from testgate import schema
        none, _ = schema.verify_claims([self.claim("포트")], "", ["a.py"])
        self.assertEqual(none, [])

    def test_at_most_twenty_claims(self):
        from testgate import schema
        desc = " ".join(f"문장{i}." for i in range(40))
        kept, _ = schema.verify_claims([self.claim(f"문장{i}.") for i in range(40)], desc, ["a.py"])
        self.assertEqual(len(kept), 20)

    def test_validate_shape_accepts_missing_claims_and_rejects_bad_ones(self):
        from testgate import schema
        base = {"mode": "design", "summary": "s", "changes": [], "notes": ""}
        self.assertEqual(schema.validate_shape(base)["description_claims"], [])
        with self.assertRaises(schema.OutputError):
            schema.validate_shape(dict(base, description_claims=[{"quote": "q", "status": "bogus", "files": []}]))
        with self.assertRaises(schema.OutputError):
            schema.validate_shape(dict(base, description_claims="nope"))

    def test_report_section_grid_and_escaping(self):
        result = design([change("a.py", scenarios=[scenario()])])
        result["description_claims"] = [
            {"quote": "포트를 <b>바꿉니다</b>", "status": "in_diff", "files": ["a.py"], "check": "a|b", "expected": "@bob"},
            {"quote": "로그인 잠금", "status": "not_in_diff", "files": [], "check": "시도", "expected": "기대"}]
        md = report.render(REQUEST, CONTEXT, result, "design", [], "[PR3]")
        self.assertIn("## PR 설명 대조", md)
        self.assertIn("<summary><b>PR 설명 대조 (2)</b></summary>", md)
        self.assertIn("| # | 설명의 주장 (원문 인용) | diff 대조 | 테스트 시도 방법 | 기대 동작 |", md)
        self.assertIn("diff에서 확인됨<br>`a.py`", md)
        self.assertIn("설명에는 있으나 diff에서 확인되지 않음", md)
        self.assertNotIn("<b>바꿉니다", md)
        self.assertIn("a\\|b", md)
        self.assertLess(md.index("PR 설명 대조"), md.index("수정된 코드"))
        out = htmlreport.render_html(REQUEST, CONTEXT, result, "design", [], "[PR3]")
        self.assertIn("PR 설명 대조 (2)", out)
        self.assertNotIn("<b>바꿉니다", out)

    def test_no_section_without_claims(self):
        md = report.render(REQUEST, CONTEXT, design([change("a.py", scenarios=[scenario()])]), "design", [], "[PR3]")
        self.assertNotIn("PR 설명 대조", md)

    def test_end_to_end_analyze_verifies_claims_against_the_pr_description(self):
        class R:
            def run(self_inner, system, user, schema_):
                self.assertIn("name=pr_description", user)
                self.assertIn(self.DESC, user)
                return {"mode": "design", "summary": "s", "notes": "", "description_claims": [
                    self.claim("포트를 7201/7202로 바꿉니다."), self.claim("지어낸 주장입니다.")],
                    "changes": [{"path": "a.py", "change_summary": "c", "tested": "unclear", "evidence_quote": "",
                                 "request": "", "scenarios": [scenario()]}]}, {"cost_usd": 0, "duration_ms": 0, "models": []}
        class K:
            def load(self_inner, context):
                return []
        ctx = {"title": "T", "body": self.DESC, "base_ref": "main", "scope": "pr", "commit": None, "head_sha": "h" * 40,
               "files": [{"path": "a.py", "status": "modified", "additions": 1, "deletions": 0, "diff_included": True, "coverage": "full", "reason": ""}],
               "diff": "diff --git a/a.py b/a.py\n--- a/a.py\n+++ b/a.py\n@@ -1 +1 @@\n+x\n", "truncated": False}
        out = analyze.analyze({"deliveryId": "d", "repo": "o/r", "pr": 3, "commit": None, "text": ""}, ctx, K(), R())
        self.assertEqual([c["quote"] for c in out["result"]["description_claims"]], ["포트를 7201/7202로 바꿉니다."])
        self.assertIn("## PR 설명 대조", out["markdown"])
        self.assertTrue(any("설명 원문에 없는 인용" in n for n in out["notes"]))


class PathWrapTest(unittest.TestCase):
    def test_grid_paths_get_break_points_after_slashes_but_other_lists_do_not(self):
        result = design([change("src/components/Nav.tsx", scenarios=[scenario()]), change("big/x.json", coverage="unseen", reason="missing", request="r")])
        md = report.render(REQUEST, CONTEXT, result, "design", [], "[PR3]")
        self.assertIn("`src/​components/​Nav.tsx`", md)
        self.assertIn("- `big/x.json`:", md)   # 목록은 그대로 둔다 (복사해서 쓰기 쉽게)

    def test_html_grid_uses_narrow_number_and_path_columns(self):
        self.assertIn("td.num, th.num { width: 2.2rem", htmlreport.STYLE)
        self.assertIn("td.path, th.path { width: 13%", htmlreport.STYLE)
        self.assertIn("td.step { width: 46%", htmlreport.STYLE)
