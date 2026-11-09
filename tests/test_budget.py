"""diff 예산 배분(budget.py) 시험. 2026-11-09 PR #1 사건(생성물이 예산을 먼저 써서 13개 파일을 못 봄)을 재현해 고정한다."""

import json
import pathlib
import unittest

from testgate import budget, diffsource, ledger

FIXTURES = pathlib.Path(__file__).parent / "fixtures"


def make_block(path, size, binary=False):
    """길이가 size 자인 가짜 diff 블록. 마지막 줄도 항상 줄바꿈으로 끝난다."""
    header = f"diff --git a/{path} b/{path}\n--- a/{path}\n+++ b/{path}\n"
    if binary:
        return f"diff --git a/{path} b/{path}\nBinary files a/{path} and b/{path} differ\n"
    out = header + "@@ -1,1 +1,1 @@\n"
    i = 0
    while len(out) < size:
        room = size - len(out)
        line = f"+line {i:05d} " + "x" * 48 + "\n"
        out += line if room >= len(line) else "+" + "y" * max(0, room - 2) + "\n"
        i += 1
    return out


def make_context(rows, scope="pr", commit=None, overrides=None):
    files, blocks = [], {}
    for r in rows:
        files.append({"path": r["path"], "status": r.get("status", "modified"), "additions": r.get("additions", 1),
                      "deletions": r.get("deletions", 0), "diff_included": True})
        blocks[r["path"]] = make_block(r["path"], r["patch_chars"], binary=r.get("binary", False))
    ctx = {"title": "t", "body": "", "base_ref": "main", "head_sha": "h" * 40, "scope": scope, "commit": commit,
           "files": files, "diff": "".join(blocks.values()), "truncated": False}
    ctx.update(overrides or {})
    return ctx, blocks


def load_rows(name):
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))["files"]


def naive_alphabetical(rows, cap):
    """옛 방식: 파일 순서대로 선착순으로 채우다가 넘치면 건너뛴다. 사건 재현용."""
    total, unseen = 0, []
    for r in rows:
        if total + r["patch_chars"] > cap:
            unseen.append(r["path"])
        else:
            total += r["patch_chars"]
    return unseen


class Pr1IncidentTest(unittest.TestCase):
    """2026-11-09 사건: 파일 50개, diff 153,454자, 상한 120,000자."""

    def setUp(self):
        self.rows = load_rows("pr1_original_shape.json")
        self.ctx, self.blocks = make_context(self.rows)

    def test_the_old_first_come_budget_loses_source_files(self):
        unseen = naive_alphabetical(self.rows, 120000)
        self.assertEqual(sum(r["patch_chars"] for r in self.rows), 153454)
        self.assertGreaterEqual(len(unseen), 5, "사건 재현: 옛 방식은 여러 파일을 놓친다 (실제 13개, 작은 파일 분포는 근사값이라 하한만 확인)")
        self.assertIn("vite.config.ts", unseen)

    def test_new_budget_reads_every_file_at_least_partially(self):
        out = budget.apply(self.ctx, {"max_diff_chars": 120000})
        self.assertEqual(out["coverage"]["unseen"], 0)
        self.assertEqual(sum(out["coverage"].values()), 50)
        self.assertLessEqual(out["diff_used"], 120000)
        self.assertEqual(out["coverage"]["excluded"], 2)

    def test_source_files_are_read_in_full_and_generated_ones_partially(self):
        out = budget.apply(self.ctx, {"max_diff_chars": 120000})
        by = {f["path"]: f for f in out["files"]}
        for path in ("vite.config.ts", "src/components/TransactionDetail.tsx", "src/components/NavDrawer.tsx",
                     "playwright.config.ts", "package.json", "Dockerfile"):
            self.assertEqual((by[path]["coverage"], by[path]["diff_included"]), ("full", True), path)
        self.assertEqual((by["pnpm-lock.yaml"]["coverage"], by["pnpm-lock.yaml"]["reason"]), ("excluded", "generated"))
        migration = "prisma/migrations/20261108224914_init/migration.sql"
        self.assertEqual((by[migration]["coverage"], by[migration]["reason"]), ("excluded", "generated"))
        # 큰 신규 파일은 전부 읽지 않고 앞뒤만 읽는다 (파일당 상한 2만 자)
        for path in ("scripts/generateTestIdList.ts", "testid-listup.md"):
            self.assertEqual((by[path]["coverage"], by[path]["reason"]), ("partial", "oversized"), path)

    def test_fingerprints_come_from_the_full_diff_not_the_excerpt(self):
        out = budget.apply(self.ctx, {"max_diff_chars": 120000})
        for f in out["files"]:
            self.assertEqual(f["fp"], ledger.fingerprint("pr", None, self.blocks[f["path"]]), f["path"])
            self.assertEqual(f["chars"], len(self.blocks[f["path"]]))

    def test_report_numbers_for_the_incident(self):
        out = budget.apply(self.ctx, {"max_diff_chars": 120000})
        self.assertEqual(out["coverage"], {"full": 46, "partial": 2, "unseen": 0, "excluded": 2})
        self.assertTrue(out["truncated"], "일부만 읽은 파일이 있으면 truncated 이다")


class GrownPrTest(unittest.TestCase):
    """같은 PR 이 100개 이상 파일, 35만 자로 커진 경우. 전부 읽을 수는 없지만 순서와 불변식은 지켜야 한다."""

    def setUp(self):
        self.rows = load_rows("pr1_grown_shape.json")
        self.ctx, _ = make_context(self.rows)
        self.out = budget.apply(self.ctx, {"max_diff_chars": 120000})

    def test_never_exceeds_the_budget_and_accounts_for_every_file(self):
        self.assertLessEqual(self.out["diff_used"], 120000)
        self.assertEqual(sum(self.out["coverage"].values()), len(self.rows))
        self.assertEqual(len(self.out["diff"]), self.out["diff_used"])

    def test_nothing_unseen_by_budget_would_still_fit(self):
        """예산 때문에 못 읽은 파일은 남은 예산보다 큰 파일뿐이다. 들어갈 수 있는 파일을 빼먹지 않았다는 뜻이다."""
        room = self.out["diff_budget"] - self.out["diff_used"]
        for f in self.out["files"]:
            if f["reason"] == "budget" and f["chars"] <= budget.DEFAULT_RULES["per_file_chars"]:
                self.assertGreater(f["chars"], room, f["path"])

    def test_every_unseen_file_has_a_reason_and_no_text(self):
        blocks = diffsource.blocks_by_path(self.out["diff"])
        for f in self.out["files"]:
            if f["coverage"] == "excluded":
                self.assertFalse(f["diff_included"])
            elif f["coverage"] == "unseen":
                self.assertFalse(f["diff_included"])
                self.assertIn(f["reason"], ("budget", "binary", "missing"))
                self.assertNotIn(f["path"], blocks)
            else:
                self.assertIn(f["path"], blocks, f["path"])


class ClassificationTest(unittest.TestCase):
    rules = budget.rules_from({})

    def test_generated(self):
        for path in ("pnpm-lock.yaml", "web/package-lock.json", "yarn.lock", "Cargo.lock", "go.sum", "uv.lock",
                     "app.min.js", "style.min.css", "bundle.js.map", "a/__snapshots__/x.test.js.snap",
                     "dist/index.js", "node_modules/x/y.js", "src/generated/api.ts", "vendor/lib.go",
                     "prisma/migrations/2026_init/migration.sql", "db/migrations/001.sql", "api.pb.go", "x_pb2.py"):
            self.assertEqual(budget.classify(path, self.rules), "generated", path)

    def test_docs(self):
        for path in ("README.md", "docs/guide.html", "docs/a.rst", "notes.txt", "LLMS.md"):
            self.assertEqual(budget.classify(path, self.rules), "doc", path)

    def test_normal_source_is_never_treated_as_generated(self):
        for path in ("src/components/NavDrawer.tsx", "scripts/generateTestIdList.ts", "package.json",
                     "playwright.config.ts", "Dockerfile", "src/build.ts", "src/lockfile.ts", "tests/test_x.py",
                     "prisma/schema.prisma", "src/migrations_helper.py", "src/mapper.js"):
            self.assertEqual(budget.classify(path, self.rules), "normal", path)

    def test_user_summary_globs_extend_the_generated_set(self):
        rules = budget.rules_from({"summary_globs": ["src/legacy/*", "*.fixture.json"]})
        self.assertEqual(budget.classify("src/legacy/old.ts", rules), "generated")
        self.assertEqual(budget.classify("data/a.fixture.json", rules), "generated")
        self.assertEqual(budget.classify("src/new/a.ts", rules), "normal")

    def test_case_insensitive_names(self):
        self.assertEqual(budget.classify("PNPM-LOCK.YAML", self.rules), "generated")
        self.assertEqual(budget.classify("Gemfile.lock", self.rules), "generated")


class BudgetBehaviorTest(unittest.TestCase):
    def rows(self, **sizes):
        return [{"path": p, "patch_chars": n} for p, n in sizes.items()]

    def apply(self, rows, settings=None, **kw):
        ctx, blocks = make_context(rows, **kw)
        return budget.apply(ctx, settings), blocks

    def test_small_pr_is_read_in_full(self):
        out, _ = self.apply(self.rows(**{"src/a.py": 500, "README.md": 300, "pnpm-lock.yaml": 400}))
        files = {f["path"]: f for f in out["files"]}
        self.assertEqual(files["src/a.py"]["coverage"], "full")
        self.assertEqual(files["README.md"]["coverage"], "full")
        # 락 파일은 작아도 일관되게 제외한다 (규칙이 크기에 따라 흔들리지 않게)
        self.assertEqual(files["pnpm-lock.yaml"]["coverage"], "excluded")

    def test_tiny_budget_keeps_source_before_docs_and_excluded_files_use_no_budget(self):
        rows = self.rows(**{"a.lock": 1500, "docs/g.md": 800, "src/s.py": 800})
        out, _ = self.apply(rows, {"max_diff_chars": 1000})
        by = {f["path"]: f for f in out["files"]}
        self.assertEqual(by["src/s.py"]["coverage"], "full")
        self.assertEqual((by["docs/g.md"]["coverage"], by["docs/g.md"]["reason"]), ("unseen", "budget"))
        self.assertEqual((by["a.lock"]["coverage"], by["a.lock"]["reason"]), ("excluded", "generated"))

    def test_original_order_is_kept_in_the_output(self):
        rows = self.rows(**{"b.lock": 500, "a/src.py": 500, "README.md": 500})
        out, _ = self.apply(rows)
        self.assertEqual([f["path"] for f in out["files"]], ["b.lock", "a/src.py", "README.md"])
        paths_in_diff = list(diffsource.blocks_by_path(out["diff"]))
        self.assertEqual(paths_in_diff, ["a/src.py", "README.md"])

    def test_oversized_file_keeps_head_tail_and_a_visible_omission_marker(self):
        out, blocks = self.apply(self.rows(**{"src/big.py": 60000}))
        f = out["files"][0]
        self.assertEqual((f["coverage"], f["reason"]), ("partial", "oversized"))
        text = diffsource.blocks_by_path(out["diff"])["src/big.py"]
        self.assertLessEqual(len(text), budget.OVERSIZED_MAX_CHARS + 300)
        self.assertTrue(text.startswith("diff --git a/src/big.py b/src/big.py\n--- a/src/big.py\n+++ b/src/big.py\n"))
        self.assertIn("[testgate] 중간", text)
        self.assertIn("생략", text)
        self.assertIn("line 00000", text, "앞부분이 있다")
        last = blocks["src/big.py"].rstrip("\n").splitlines()[-1]
        self.assertIn(last, text, "뒷부분이 있다")

    def test_excluded_files_are_not_read_at_all(self):
        out, _ = self.apply(self.rows(**{"pnpm-lock.yaml": 40000, "a.py": 300}))
        self.assertNotIn("pnpm-lock.yaml", diffsource.blocks_by_path(out["diff"]))
        self.assertEqual(out["coverage"], {"full": 1, "partial": 0, "unseen": 0, "excluded": 1})
        self.assertFalse(out["truncated"], "제외는 누락이 아니다")

    def test_full_globs_overrides_generated_and_oversized(self):
        rows = self.rows(**{"pnpm-lock.yaml": 8000, "src/big.py": 30000})
        out, blocks = self.apply(rows, {"full_globs": ["pnpm-lock.yaml", "src/big.py"], "max_diff_chars": 200000})
        for f in out["files"]:
            self.assertEqual(f["coverage"], "full", f["path"])
        self.assertEqual(out["diff"], blocks["pnpm-lock.yaml"] + blocks["src/big.py"])

    def test_full_globs_still_respects_the_total_budget(self):
        out, _ = self.apply(self.rows(**{"src/big.py": 30000}), {"full_globs": ["src/*"], "max_diff_chars": 10000})
        self.assertEqual((out["files"][0]["coverage"], out["files"][0]["reason"]), ("unseen", "budget"))

    def test_binary_files_are_unseen_with_a_fingerprint(self):
        rows = [{"path": "img/logo.png", "patch_chars": 10, "binary": True}, {"path": "a.py", "patch_chars": 300}]
        out, blocks = self.apply(rows)
        f = out["files"][0]
        self.assertEqual((f["coverage"], f["reason"], f["diff_included"]), ("unseen", "binary", False))
        self.assertEqual(f["fp"], ledger.fingerprint("pr", None, blocks["img/logo.png"]))

    def test_files_without_a_diff_are_unseen_missing(self):
        ctx, _ = make_context(self.rows(**{"a.py": 300, "b.py": 300}))
        ctx["files"][1]["diff_included"] = False   # github-app 이 너무 커서 빼 버린 경우
        ctx["files"].append({"path": "c.py", "status": "added", "additions": 1, "deletions": 0, "diff_included": True})
        out = budget.apply(ctx)
        by = {f["path"]: f for f in out["files"]}
        for p in ("b.py", "c.py"):
            self.assertEqual((by[p]["coverage"], by[p]["reason"], by[p]["fp"]), ("unseen", "missing", None), p)
        self.assertEqual(by["a.py"]["coverage"], "full")

    def test_deterministic_and_input_is_not_mutated(self):
        ctx, _ = make_context(self.rows(**{"pnpm-lock.yaml": 9000, "a.py": 500, "README.md": 400}))
        before = json.dumps(ctx, sort_keys=True)
        first, second = budget.apply(ctx), budget.apply(ctx)
        self.assertEqual(json.dumps(first, sort_keys=True), json.dumps(second, sort_keys=True))
        self.assertEqual(json.dumps(ctx, sort_keys=True), before)

    def test_commit_scope_changes_the_fingerprint(self):
        rows = self.rows(**{"a.py": 500})
        pr, _ = self.apply(rows)
        commit, _ = self.apply(rows, scope="commit", commit="abc1234")
        self.assertNotEqual(pr["files"][0]["fp"], commit["files"][0]["fp"])

    def test_truncated_is_false_only_when_everything_is_full(self):
        out, _ = self.apply(self.rows(**{"a.py": 500, "b.py": 500}))
        self.assertFalse(out["truncated"])
        self.assertEqual(out["coverage"], {"full": 2, "partial": 0, "unseen": 0, "excluded": 0})

    def test_incoming_truncated_flag_is_preserved(self):
        ctx, _ = make_context(self.rows(**{"a.py": 500}), overrides={"truncated": True})
        self.assertTrue(budget.apply(ctx)["truncated"])

    def test_very_long_lines_are_cut_by_characters_with_an_honest_marker(self):
        block = "diff --git a/src/x.txt b/src/x.txt\n--- a/src/x.txt\n+++ b/src/x.txt\n@@ -1 +1 @@\n+" + "z" * 50000 + "\n"
        ctx = {"title": "", "body": "", "base_ref": "main", "head_sha": "h", "scope": "pr", "commit": None, "truncated": False,
               "files": [{"path": "src/x.txt", "status": "modified", "additions": 1, "deletions": 0, "diff_included": True}],
               "diff": block}
        out = budget.apply(ctx)
        text = out["diff"]
        self.assertIn("문자 수 상한으로 뒤쪽 생략", text)
        self.assertNotIn("0줄 생략", text)
        self.assertLessEqual(len(text), budget.OVERSIZED_MAX_CHARS + 300)

    def test_legacy_apply_limit_delegates(self):
        ctx, _ = make_context(self.rows(**{"a.py": 500, "b.lock": 500}))
        out = diffsource.apply_limit(ctx, 100000)
        self.assertIn("coverage", out)
        self.assertEqual(out["coverage"]["excluded"], 1)

    def test_coverage_of_legacy_contexts(self):
        self.assertEqual(budget.coverage_of({"diff_included": True}), "full")
        self.assertEqual(budget.coverage_of({"diff_included": False}), "unseen")
        self.assertEqual(budget.coverage_of({"coverage": "partial", "diff_included": True}), "partial")
        self.assertEqual(budget.reason_label("budget"), budget.REASON_LABELS["budget"])


if __name__ == "__main__":
    unittest.main()


class AnalyzeCoverageTest(unittest.TestCase):
    """budget 결과가 분석, 보고서, 기록까지 이어지는지 본다. Claude 대신 가짜 실행기를 쓴다."""

    class Runner:
        def __init__(self, tested="yes"):
            self.calls, self.tested = [], tested

        def run(self, system, user, schema_):
            self.calls.append(user)
            import re
            paths = re.search(r"name=files_to_evaluate id=\w+>>>\n(.*?)\n<<<END", user, re.S).group(1).splitlines()
            quote = "a.py 검증함"
            changes = [{"path": ln.split("  ")[0], "change_summary": "요약", "tested": self.tested,
                        "evidence_quote": quote, "request": "", "scenarios": []} for ln in paths]
            return {"mode": "evaluate", "summary": "요약", "changes": changes, "notes": ""}, \
                {"cost_usd": 0, "duration_ms": 0, "models": []}

    class Knowledge:
        def load(self, context):
            return []

    def run_analyze(self, rows, budget_chars, tested="yes", text="a.py 검증함 pnpm-lock.yaml 검증함"):
        from testgate import analyze
        ctx, _ = make_context(rows)
        ctx = budget.apply(ctx, {"max_diff_chars": budget_chars})
        runner = self.Runner(tested)
        request = {"deliveryId": "d", "repo": "o/r", "pr": 1, "commit": None, "text": text}
        return analyze.analyze(request, ctx, self.Knowledge(), runner), runner

    def test_unseen_files_get_no_judgement_no_scenarios_and_no_prompt_text(self):
        rows = [{"path": "a.py", "patch_chars": 800}, {"path": "b.py", "patch_chars": 800}]
        out, runner = self.run_analyze(rows, 900)
        by = {c["path"]: c for c in out["result"]["changes"]}
        self.assertEqual(by["b.py"]["coverage"], "unseen")
        self.assertEqual(by["b.py"]["tested"], "unclear")
        self.assertEqual(by["b.py"]["scenarios"], [])
        self.assertNotIn("b.py", runner.calls[0].split("name=files_to_evaluate")[1].split("<<<END")[0])
        self.assertIn("## 확인하지 못한 파일", out["markdown"])
        self.assertIn("diff 예산을 넘어 읽지 못함", out["markdown"])
        self.assertIn("판독 범위: 전체 1, 일부 0, 제외 0, 미확인 1", out["markdown"])
        self.assertEqual(out["files_record"]["b.py"]["coverage"], "unseen")
        self.assertEqual(out["verdict"], "more_tests_needed")

    def test_pending_requests_exclude_unseen_files(self):
        rows = [{"path": "a.py", "patch_chars": 800}, {"path": "b.py", "patch_chars": 800}]
        out, _ = self.run_analyze(rows, 900, tested="no")
        section = out["markdown"].split("## 추가로 이행해야 할 테스트")[1].split("## 확인하지 못한 파일")[0]
        self.assertIn("a.py", section)
        self.assertNotIn("b.py", section)

    def test_partial_files_cannot_be_verified(self):
        rows = [{"path": "src/big.py", "patch_chars": 30000}]
        out, runner = self.run_analyze(rows, 50000, text="src/big.py 검증함 a.py 검증함")
        change = out["result"]["changes"][0]
        self.assertEqual((change["coverage"], change["tested"]), ("partial", "partial"))
        self.assertIn("(partial: oversized)", runner.calls[0])
        self.assertIn("## 일부만 읽은 파일", out["markdown"])
        self.assertEqual(out["verdict"], "more_tests_needed")

    def test_excluded_files_are_listed_and_do_not_block_sufficient(self):
        rows = [{"path": "a.py", "patch_chars": 400}, {"path": "pnpm-lock.yaml", "patch_chars": 9000}]
        out, runner = self.run_analyze(rows, 50000)
        self.assertEqual(out["verdict"], "sufficient")
        self.assertIn("## 분석에서 제외한 파일", out["markdown"])
        self.assertIn("제외 1", out["markdown"])
        self.assertNotIn("pnpm-lock.yaml", runner.calls[0].split("name=files_to_evaluate")[1].split("<<<END")[0])
        section = out["markdown"].split("## 분석에서 제외한 파일")[1]
        self.assertIn("`pnpm-lock.yaml`", section)

    def test_free_prompt_carries_the_rules_and_coverage_marks(self):
        from testgate import prompt
        ctx, _ = make_context([{"path": "pnpm-lock.yaml", "patch_chars": 900}, {"path": "a.py", "patch_chars": 300}])
        ctx = budget.apply(ctx)
        out = prompt.build_free_prompt({"text": "eslint 제외해"}, dict(ctx, diff=""), [], "", rules=budget.rules_text())
        self.assertIn("name=analysis_rules", out)
        self.assertIn("pnpm-lock.yaml  +1 -0 (excluded by rule)", out)
        self.assertIn("summary_globs", out)

    def test_claude_is_not_called_when_nothing_is_readable(self):
        rows = [{"path": "a.py", "patch_chars": 800}]
        out, runner = self.run_analyze(rows, 100)
        self.assertEqual(runner.calls, [])
        self.assertEqual(out["result"]["changes"][0]["coverage"], "unseen")

    def test_design_mode_marks_scenarios_as_a_hypothesis(self):
        from testgate import report
        result = {"mode": "design", "summary": "s", "notes": "", "changes": [
            {"path": "a.py", "change_summary": "x", "tested": "unclear", "evidence_quote": "", "request": "",
             "scenarios": [], "coverage": "full", "reason": ""},
            {"path": "b.py", "change_summary": "y", "tested": "unclear", "evidence_quote": "", "request": "",
             "scenarios": [], "coverage": "unseen", "reason": "budget"}]}
        md = report.render({"pr": 1}, {"base_ref": "main"}, result, "design", [], "[PR1]")
        self.assertIn("가설 초안입니다. 중요도는 검증하지 않았습니다.", md)
        self.assertNotIn("### `b.py`", md)
        self.assertIn("## 확인하지 못한 파일", md)


class RulesDocAndConfigTest(unittest.TestCase):
    def test_hermes_guide_lists_every_builtin_exclusion(self):
        doc = (pathlib.Path(__file__).parent.parent / "docs" / "hermes-guide.md").read_text(encoding="utf-8").lower()
        for item in sorted(budget.GENERATED_NAMES) + list(budget.GENERATED_SUFFIXES) + sorted(budget.GENERATED_DIRS):
            self.assertIn(item.lower(), doc, f"docs/hermes-guide.md 에 제외 규칙 {item} 이 없다")

    def test_malformed_glob_settings_fall_back_to_defaults(self):
        import tempfile
        from testgate import config
        cases = {"summary_globs": "*", "full_globs": [1], "max_diff_chars": "100", "per_file_chars": 0, "timeout_seconds": True}
        with tempfile.TemporaryDirectory() as tmp:
            path = pathlib.Path(tmp) / "testgate.json"
            path.write_text(json.dumps({"analysis": cases}), encoding="utf-8")
            settings = config.load_analysis_config(path)
        for key in cases:
            self.assertEqual(settings[key], config.DEFAULTS[key], key)

    def test_valid_glob_settings_are_used_end_to_end(self):
        import tempfile
        from testgate import config
        with tempfile.TemporaryDirectory() as tmp:
            path = pathlib.Path(tmp) / "testgate.json"
            path.write_text(json.dumps({"analysis": {"summary_globs": ["eslint*"]}}), encoding="utf-8")
            settings = config.load_analysis_config(path)
        ctx, _ = make_context([{"path": "eslint.config.js", "patch_chars": 400}, {"path": "a.py", "patch_chars": 400}])
        by = {f["path"]: f["coverage"] for f in budget.apply(ctx, settings)["files"]}
        self.assertEqual(by, {"eslint.config.js": "excluded", "a.py": "full"})


class FairFillTest(unittest.TestCase):
    def test_small_files_are_not_starved_by_a_big_file_that_sorts_first(self):
        rows = [{"path": "backend/big.ts", "patch_chars": 15000}] + [
            {"path": f"src/components/C{i:02d}.tsx", "patch_chars": 800} for i in range(20)]
        ctx, _ = make_context(rows)
        out = budget.apply(ctx, {"max_diff_chars": 16000})
        by = {f["path"]: f["coverage"] for f in out["files"]}
        self.assertEqual(sum(1 for p, c in by.items() if p.startswith("src/") and c == "full"), 20)
        self.assertEqual(by["backend/big.ts"], "unseen")
        self.assertLessEqual(out["diff_used"], 16000)

    def test_tier_still_beats_size(self):
        rows = [{"path": "docs/tiny.md", "patch_chars": 100}, {"path": "src/a.py", "patch_chars": 900}]
        ctx, _ = make_context(rows)
        by = {f["path"]: f["coverage"] for f in budget.apply(ctx, {"max_diff_chars": 950})["files"]}
        self.assertEqual((by["src/a.py"], by["docs/tiny.md"]), ("full", "unseen"))

    def test_default_budget_reads_the_whole_pr1_shape(self):
        ctx, _ = make_context(load_rows("pr1_grown_shape.json"))
        out = budget.apply(ctx)
        self.assertEqual(budget.DEFAULT_RULES["max_diff_chars"], 400000)
        self.assertEqual(out["coverage"]["unseen"], 0, out["coverage"])
