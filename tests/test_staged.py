"""단계식 가져오기(목록 먼저, 본문은 필요한 파일만)를 시험한다. github-app 대역은 manifest/paths 옵션을 이해한다."""

import hashlib
import hmac
import json
import threading
import unittest
from http.server import BaseHTTPRequestHandler, HTTPServer

from testgate import budget, githubapp

SECRET = "k"
HEAD = "a" * 40


def block(path, size):
    body = "".join(f"+row {i:05d}\n" for i in range(size // 11 + 1))
    return f"diff --git a/{path} b/{path}\n--- a/{path}\n+++ b/{path}\n@@ -1 +1 @@\n{body}"


class Dataset:
    files = {}      # path -> block 또는 None(GitHub이 본문을 주지 않음)
    log = []
    head = HEAD
    change_head_after_first_paths = False
    legacy = False


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def do_POST(self):
        raw = self.rfile.read(int(self.headers["content-length"]))
        ts = self.headers.get("x-hermes-timestamp", "")
        want = "sha256=" + hmac.new(SECRET.encode(), f"{ts}.".encode() + raw, hashlib.sha256).hexdigest()
        if not hmac.compare_digest(self.headers.get("x-hermes-signature", ""), want):
            return self.send(401, {"error": "invalid_signature"})
        req = json.loads(raw)
        Dataset.log.append(req)
        common = {"title": "T", "body": "B", "base_ref": "main", "head_sha": Dataset.head, "scope": "pr", "commit": None}
        def entry(path, included, omitted=None):
            b = Dataset.files[path]
            return {"path": path, "status": "modified", "additions": 1, "deletions": 0,
                    "patch_chars": len(b) if b else 0, "omitted": omitted, "diff_included": included}
        if Dataset.legacy or not ("manifest" in req or "paths" in req):
            files = [dict(entry(p, Dataset.files[p] is not None), omitted=None) for p in Dataset.files]
            diff = "".join(b for b in Dataset.files.values() if b)
            return self.send(200, dict(common, files=files, diff=diff, truncated=False))
        if "head_sha" in req and Dataset.head != req["head_sha"]:
            return self.send(409, {"error": "head_changed"})
        if req.get("manifest"):
            files = [entry(p, False, None if Dataset.files[p] else "no_patch") for p in Dataset.files]
            return self.send(200, dict(common, manifest=True, files=files, diff="", truncated=False))
        files, diff = [], ""
        for p in req["paths"]:
            b = Dataset.files[p]
            files.append(entry(p, bool(b), None if b else "no_patch"))
            diff += b or ""
        if Dataset.change_head_after_first_paths:
            Dataset.head = "b" * 40
            Dataset.change_head_after_first_paths = False
        return self.send(200, dict(common, manifest=False, files=files, diff=diff, truncated=any(not f["diff_included"] for f in files)))

    def send(self, status, data):
        raw = json.dumps(data).encode()
        self.send_response(status)
        self.send_header("content-length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)


class StagedTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = HTTPServer(("127.0.0.1", 0), Handler)
        threading.Thread(target=cls.server.serve_forever, daemon=True).start()
        cls.port = cls.server.server_address[1]

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()

    def setUp(self):
        Dataset.files = {"a.py": block("a.py", 500), "pnpm-lock.yaml": block("pnpm-lock.yaml", 50000),
                         "big.json": None, "b.py": block("b.py", 700)}
        Dataset.log, Dataset.head, Dataset.legacy, Dataset.change_head_after_first_paths = [], HEAD, False, False
        self.app = githubapp.GithubApp(f"http://127.0.0.1:{self.port}", SECRET, timeout=5)

    def fetch(self, **kw):
        return self.app.fetch_context("o/r", 3, select=lambda files: budget.paths_to_fetch(files), **kw)

    def test_excluded_and_bodyless_files_are_not_requested(self):
        ctx = self.fetch()
        paths_requests = [r["paths"] for r in Dataset.log if "paths" in r]
        self.assertEqual(paths_requests, [["a.py", "b.py"]])
        self.assertTrue(Dataset.log[0]["manifest"])
        self.assertEqual(Dataset.log[1]["head_sha"], HEAD)
        self.assertEqual([f["path"] for f in ctx["files"]], ["a.py", "pnpm-lock.yaml", "big.json", "b.py"])
        self.assertEqual([f["diff_included"] for f in ctx["files"]], [True, False, False, True])
        self.assertEqual(ctx["diff"], Dataset.files["a.py"] + Dataset.files["b.py"])
        self.assertTrue(ctx["truncated"])

    def test_budget_labels_each_kind_correctly(self):
        out = budget.apply(self.fetch())
        by = {f["path"]: (f["coverage"], f["reason"]) for f in out["files"]}
        self.assertEqual(by, {"a.py": ("full", ""), "pnpm-lock.yaml": ("excluded", "generated"),
                              "big.json": ("unseen", "missing"), "b.py": ("full", "")})
        self.assertIn("너무 큰 변경", budget.reason_label("missing"))

    def test_bodies_are_fetched_in_batches(self):
        self.fetch(batch_chars=600)
        self.assertEqual([r["paths"] for r in Dataset.log if "paths" in r], [["a.py"], ["b.py"]])

    def test_new_commit_during_fetch_restarts_once(self):
        Dataset.change_head_after_first_paths = True
        ctx = self.fetch(batch_chars=600)
        self.assertEqual(ctx["head_sha"], "b" * 40)
        self.assertEqual(sum(1 for r in Dataset.log if r.get("manifest")), 2)

    def test_old_github_app_falls_back_to_one_shot(self):
        Dataset.legacy = True
        ctx = self.fetch()
        self.assertEqual(len(Dataset.log), 1)
        self.assertEqual(ctx["diff"], "".join(b for b in Dataset.files.values() if b))

    def test_without_select_the_old_one_shot_request_is_sent(self):
        self.app.fetch_context("o/r", 3)
        self.assertEqual(Dataset.log, [{"repo": "o/r", "pr": 3}])

    def test_pr1_shape_reads_all_non_excluded_files(self):
        rows = json.loads((__import__("pathlib").Path(__file__).parent / "fixtures" / "pr1_grown_shape.json").read_text())["files"]
        Dataset.files = {r["path"]: (block(r["path"], r["patch_chars"]) if r["patch_chars"] else None) for r in rows}
        out = budget.apply(self.fetch())
        counts = out["coverage"]
        self.assertEqual(counts["unseen"] + counts["partial"] + counts["full"] + counts["excluded"], len(rows))
        requested = {p for r in Dataset.log if "paths" in r for p in r["paths"]}
        self.assertFalse(any(p in requested for p in Dataset.files if budget.classify(p, budget.rules_from({})) == "generated"))


if __name__ == "__main__":
    unittest.main()
