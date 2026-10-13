import unittest

from testgate import schema


def change(path, tested="yes", quote="", request="", scenarios=None):
    return {"path": path, "change_summary": "s", "tested": tested, "evidence_quote": quote,
            "request": request, "scenarios": scenarios or []}


def output(changes, mode="evaluate"):
    return {"mode": mode, "summary": "요약", "changes": changes, "notes": ""}


FILES = [{"path": "a.py", "diff_included": True}, {"path": "b.py", "diff_included": True}]
TEXT = "로그를 확인했고  a.py 의 모킹 여부를 확인했다."


class ShapeTest(unittest.TestCase):
    def test_valid(self):
        self.assertEqual(schema.validate_shape(output([change("a.py")]))["mode"], "evaluate")

    def test_rejects_bad_values(self):
        for raw in (None, [], {"mode": "x"}, output([change("a", tested="maybe")]),
                    {"mode": "evaluate", "summary": "s", "changes": "no", "notes": ""},
                    output([{"path": "a"}])):
            with self.assertRaises(schema.OutputError):
                schema.validate_shape(raw)

    def test_long_fields_are_cut(self):
        raw = output([change("a.py")])
        raw["summary"] = "가" * 5000
        self.assertEqual(len(schema.validate_shape(raw)["summary"]), schema.MAX_FIELD_CHARS)


class PostprocessTest(unittest.TestCase):
    def run_pp(self, changes, text=TEXT, files=FILES, mode="evaluate"):
        return schema.postprocess(schema.validate_shape(output(changes, mode)), files, text)

    def test_missing_file_is_added_as_unclear(self):
        result, notes = self.run_pp([change("a.py", quote="a.py 의 모킹 여부를 확인했다")])
        self.assertEqual([c["path"] for c in result["changes"]], ["a.py", "b.py"])
        self.assertEqual(result["changes"][1]["tested"], "unclear")
        self.assertTrue(any("b.py" in n for n in notes))
        self.assertTrue(result["changes"][1]["request"])

    def test_unknown_path_is_dropped(self):
        result, notes = self.run_pp([change("a.py", "no"), change("b.py", "no"), change("evil.py", "yes", "x")])
        self.assertEqual([c["path"] for c in result["changes"]], ["a.py", "b.py"])
        self.assertTrue(notes)

    def test_duplicate_path_keeps_first(self):
        result, _ = self.run_pp([change("a.py", "no", request="r"), change("a.py", "yes", "로그를 확인했고"), change("b.py", "no")])
        self.assertEqual(result["changes"][0]["tested"], "no")

    def test_quote_must_exist_in_text_whitespace_insensitive(self):
        result, _ = self.run_pp([change("a.py", "yes", "로그를   확인했고 a.py"), change("b.py", "no")])
        self.assertEqual(result["changes"][0]["tested"], "yes")

    def test_fabricated_quote_is_downgraded(self):
        result, notes = self.run_pp([change("a.py", "yes", "모든 테스트를 통과했다"), change("b.py", "no")])
        self.assertEqual(result["changes"][0]["tested"], "unclear")
        self.assertEqual(result["changes"][0]["evidence_quote"], "")
        self.assertTrue(any("근거 인용" in n for n in notes))

    def test_empty_quote_with_yes_is_downgraded(self):
        result, _ = self.run_pp([change("a.py", "yes", ""), change("b.py", "no")])
        self.assertEqual(result["changes"][0]["tested"], "unclear")

    def test_empty_text_forces_design(self):
        result, notes = self.run_pp([change("a.py", "yes", "x"), change("b.py", "no")], text="  \n")
        self.assertEqual(result["mode"], "design")
        self.assertTrue(any("설계서" in n for n in notes))

    def test_omitted_diff_is_unclear(self):
        files = [{"path": "a.py", "diff_included": True}, {"path": "b.py", "diff_included": False}]
        result, _ = self.run_pp([change("a.py", "no"), change("b.py", "yes", "로그를 확인했고")], files=files)
        self.assertEqual(result["changes"][1]["tested"], "unclear")

    def test_design_mode_does_not_check_quotes(self):
        result, _ = self.run_pp([change("a.py", "unclear"), change("b.py", "unclear")], mode="design")
        self.assertEqual(result["mode"], "design")


class VerdictTest(unittest.TestCase):
    def test_verdicts(self):
        yes = {"mode": "evaluate", "changes": [{"tested": "yes"}, {"tested": "yes"}]}
        self.assertEqual(schema.verdict(yes), "sufficient")
        partial = {"mode": "evaluate", "changes": [{"tested": "yes"}, {"tested": "partial"}]}
        self.assertEqual(schema.verdict(partial), "more_tests_needed")
        self.assertEqual(schema.verdict({"mode": "evaluate", "changes": []}), "more_tests_needed")
        self.assertEqual(schema.verdict({"mode": "design", "changes": []}), "design")


if __name__ == "__main__":
    unittest.main()
