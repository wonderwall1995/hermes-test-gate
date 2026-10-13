import pathlib
import subprocess
import tempfile
import unittest

from testgate import diffsource


def git(repo, *args):
    subprocess.run(["git", "-C", repo, "-c", "user.name=t", "-c", "user.email=t@example.invalid", *args],
                   check=True, capture_output=True, text=True)


class LocalGitSourceTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.repo = cls.tmp.name
        root = pathlib.Path(cls.repo)
        git(cls.repo, "init", "-q", "-b", "main")
        (root / "a.txt").write_text("one\n")
        (root / "b.txt").write_text("keep\n")
        git(cls.repo, "add", ".")
        git(cls.repo, "commit", "-q", "-m", "base")
        git(cls.repo, "checkout", "-q", "-b", "feature")
        (root / "a.txt").write_text("one\ntwo\n")
        git(cls.repo, "commit", "-q", "-am", "c1")
        (root / "c.txt").write_text("new\n")
        git(cls.repo, "add", ".")
        git(cls.repo, "commit", "-q", "-m", "c2")
        cls.first = subprocess.run(["git", "-C", cls.repo, "rev-parse", "HEAD~1"], capture_output=True, text=True).stdout.strip()

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def test_pr_scope_combines_all_commits(self):
        ctx = diffsource.LocalGitSource(self.repo).get("main", "feature", title="t", body="b")
        self.assertEqual(ctx["scope"], "pr")
        self.assertEqual([f["path"] for f in ctx["files"]], ["a.txt", "c.txt"])
        self.assertIn("+two", ctx["diff"])
        self.assertIn("+new", ctx["diff"])
        self.assertFalse(ctx["truncated"])
        self.assertTrue(all(f["diff_included"] for f in ctx["files"]))

    def test_commit_scope_shows_only_that_commit(self):
        ctx = diffsource.LocalGitSource(self.repo).get("main", "feature", commit=self.first)
        self.assertEqual(ctx["scope"], "commit")
        self.assertEqual([f["path"] for f in ctx["files"]], ["a.txt"])
        self.assertNotIn("+new", ctx["diff"])

    def test_diff_limit_marks_omitted_files(self):
        full = diffsource.LocalGitSource(self.repo).get("main", "feature")
        first_block = diffsource.split_diff_by_file(full["diff"])[0]
        # 첫 블록은 들어가고 둘째 블록은 들어가지 않는 상한
        ctx = diffsource.LocalGitSource(self.repo, max_diff_chars=len(first_block) + 1).get("main", "feature")
        self.assertTrue(ctx["truncated"])
        flags = {f["path"]: f["diff_included"] for f in ctx["files"]}
        self.assertTrue(flags["a.txt"])
        self.assertFalse(flags["c.txt"])

    def test_bad_refs_are_rejected(self):
        src = diffsource.LocalGitSource(self.repo)
        for bad in ("--output=x", "-p", "a..b", "x y", "", "a;b"):
            with self.assertRaises(diffsource.DiffSourceError, msg=bad):
                src.get(bad, "feature")
            with self.assertRaises(diffsource.DiffSourceError, msg=bad):
                src.get("main", bad)

    def test_unknown_ref_fails_cleanly(self):
        with self.assertRaises(diffsource.DiffSourceError):
            diffsource.LocalGitSource(self.repo).get("main", "nope")


if __name__ == "__main__":
    unittest.main()
