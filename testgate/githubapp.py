"""github-app의 Hermes 연동 API(/api/pr, /api/comment, /api/comment/update) 클라이언트.

요청 서명: x-hermes-timestamp(초) 와 x-hermes-signature = "sha256=" + HMAC-SHA256("<timestamp>.<바디>").
"""

import hashlib
import re
import hmac
import json
import time
import urllib.error
import urllib.request

from testgate import diffsource

DEFAULT_URL = "http://127.0.0.1:3200"
REPORT_URL = re.compile(r"^https://[A-Za-z0-9.-]+(:[0-9]{1,5})?/r/[A-Za-z0-9_-]{43}$")
BATCH_CHARS = 600000   # 한 번에 받는 본문 크기(파일 크기 합계). github-app의 한 응답 상한(100만 자)보다 작게 둔다


class GithubAppError(diffsource.DiffSourceError):
    """github-app 호출이 실패했을 때 발생한다. 메시지에 비밀 값은 넣지 않는다."""


def sign_request(secret, timestamp, body):
    signed = f"{timestamp}.".encode() + body
    return "sha256=" + hmac.new(secret.encode(), signed, hashlib.sha256).hexdigest()


class GithubApp:
    def __init__(self, url=DEFAULT_URL, secret="", timeout=30, now=time.time):
        if not secret:
            raise GithubAppError("github_app_secret이 설정되어 있지 않다")
        self.url = url.rstrip("/")
        self.secret = secret
        self.timeout = timeout
        self.now = now

    def _post(self, path, payload):
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        timestamp = str(int(self.now()))
        request = urllib.request.Request(
            self.url + path, data=body, method="POST",
            headers={
                "content-type": "application/json",
                "x-hermes-timestamp": timestamp,
                "x-hermes-signature": sign_request(self.secret, timestamp, body),
            },
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                return json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            code = ""
            try:
                code = json.loads(exc.read().decode("utf-8")).get("error", "")
            except (ValueError, OSError):
                pass
            finally:
                exc.close()
            raise GithubAppError(f"github-app 응답 오류 {exc.code} {code}".strip())
        except (urllib.error.URLError, OSError, ValueError) as exc:
            raise GithubAppError(f"github-app에 연결할 수 없다: {exc.__class__.__name__}")

    def _context_from(self, data):
        """/api/pr 응답을 분석기가 쓰는 형태로 바꾼다."""
        try:
            return {
                "title": str(data["title"]),
                "body": str(data["body"]),
                "base_ref": str(data["base_ref"]),
                "head_sha": str(data["head_sha"]),
                "scope": str(data["scope"]),
                "commit": data.get("commit"),
                "files": [
                    {
                        "path": str(f["path"]), "status": str(f["status"]),
                        "additions": int(f["additions"]), "deletions": int(f["deletions"]),
                        "diff_included": bool(f["diff_included"]),
                        "patch_chars": int(f.get("patch_chars", 0)),
                        "omitted": f.get("omitted") if f.get("omitted") in ("no_patch", "size_cap") else None,
                    }
                    for f in data["files"]
                ],
                "diff": str(data["diff"]),
                "truncated": bool(data["truncated"]),
            }
        except (KeyError, TypeError, ValueError):
            raise GithubAppError("github-app 응답 형식이 올바르지 않다")

    def fetch_context(self, repo, pr, commit=None, select=None, batch_chars=BATCH_CHARS):
        """PR 맥락을 분석기가 쓰는 형태로 돌려준다.

        select가 있으면 단계식으로 가져온다. 먼저 파일 목록(본문 없음)을 받고, select(files)가 돌려준 경로의
        본문만 묶음으로 나눠 받는다. 서버가 단계식을 지원하지 않으면(옛 github-app) 한 번에 받는 방식으로 돌아간다.
        """
        base = {"repo": repo, "pr": pr}
        if commit:
            base["commit"] = commit
        if select is None:
            return self._context_from(self._post("/api/pr", base))
        for attempt in range(2):
            data = self._post("/api/pr", dict(base, manifest=True))
            if data.get("manifest") is not True:
                return self._context_from(data)   # 옛 서버는 옵션을 무시하고 전체를 준다
            context = self._context_from(data)
            wanted = [p for p in select(context["files"]) if isinstance(p, str)]
            try:
                return self._fetch_bodies(base, context, wanted, batch_chars)
            except GithubAppError as exc:
                if "head_changed" in str(exc) and attempt == 0:
                    continue  # 요청하는 동안 새 커밋이 올라오면 처음부터 한 번 더
                raise
        raise GithubAppError("github-app 응답 오류 409 head_changed")

    def _fetch_bodies(self, base, context, wanted, batch_chars):
        sizes = {f["path"]: f["patch_chars"] for f in context["files"]}
        batches, current, used = [], [], 0
        for path in wanted:
            size = sizes.get(path, 0)
            if current and used + size > batch_chars:
                batches.append(current)
                current, used = [], 0
            current.append(path)
            used += size
        if current:
            batches.append(current)
        blocks, flags = {}, {}
        for paths in batches:
            data = self._post("/api/pr", dict(base, paths=paths, head_sha=context["head_sha"]))
            part = self._context_from(data)
            if part["head_sha"] != context["head_sha"]:
                raise GithubAppError("github-app 응답 오류 409 head_changed")
            for f in part["files"]:
                flags[f["path"]] = f
            for path, block in diffsource.blocks_by_path(part["diff"]).items():
                blocks[path] = block
        files = []
        for f in context["files"]:
            got = flags.get(f["path"])
            if got is not None:
                f = dict(f, diff_included=got["diff_included"], omitted=got["omitted"])
            files.append(f)
        diff = "".join(blocks[f["path"]] for f in files if f["path"] in blocks and f["diff_included"])
        return dict(context, files=files, diff=diff, truncated=any(not f["diff_included"] for f in files))

    def upload_report(self, repo, pr, html, delivery_id):
        """HTML 보고서를 보관소에 올리고 내려받는 주소를 돌려준다. 같은 delivery_id는 한 번만 올라간다."""
        data = self._post("/api/report", {"repo": repo, "pr": pr, "html": html, "deliveryId": delivery_id})
        url = data.get("url") if isinstance(data, dict) else None
        if not isinstance(url, str) or not REPORT_URL.match(url):
            raise GithubAppError("github-app 응답 형식이 올바르지 않다")
        return url

    def post_comment_ref(self, repo, pr, body, delivery_id):
        """PR에 코멘트를 게시하고 (URL, 코멘트 id)를 돌려준다. 같은 delivery_id는 한 번만 게시된다.

        옛 github-app은 코멘트 id를 주지 않으므로 그 경우 id는 None이다.
        """
        data = self._post("/api/comment", {"repo": repo, "pr": pr, "body": body, "deliveryId": delivery_id})
        url = data.get("url") if isinstance(data, dict) else None
        if not isinstance(url, str):
            raise GithubAppError("github-app 응답 형식이 올바르지 않다")
        comment_id = data.get("commentId")
        if isinstance(comment_id, bool) or not isinstance(comment_id, int) or comment_id <= 0:
            comment_id = None
        return url, comment_id

    def post_comment(self, repo, pr, body, delivery_id):
        """PR에 코멘트를 게시하고 URL을 돌려준다. 같은 delivery_id는 한 번만 게시된다."""
        return self.post_comment_ref(repo, pr, body, delivery_id)[0]

    def update_comment(self, repo, pr, comment_id, body):
        """이 앱이 먼저 게시한 코멘트를 고치고 URL을 돌려준다."""
        data = self._post("/api/comment/update", {"repo": repo, "pr": pr, "commentId": comment_id, "body": body})
        url = data.get("url") if isinstance(data, dict) else None
        if not isinstance(url, str):
            raise GithubAppError("github-app 응답 형식이 올바르지 않다")
        return url
