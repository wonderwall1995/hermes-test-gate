"""github-app의 Hermes 연동 API(/api/pr, /api/comment) 클라이언트.

요청 서명: x-hermes-timestamp(초) 와 x-hermes-signature = "sha256=" + HMAC-SHA256("<timestamp>.<바디>").
"""

import hashlib
import hmac
import json
import time
import urllib.error
import urllib.request

from testgate import diffsource

DEFAULT_URL = "http://127.0.0.1:3200"


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

    def fetch_context(self, repo, pr, commit=None):
        """PR 맥락을 분석기가 쓰는 형태로 돌려준다."""
        payload = {"repo": repo, "pr": pr}
        if commit:
            payload["commit"] = commit
        data = self._post("/api/pr", payload)
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
                    }
                    for f in data["files"]
                ],
                "diff": str(data["diff"]),
                "truncated": bool(data["truncated"]),
            }
        except (KeyError, TypeError, ValueError):
            raise GithubAppError("github-app 응답 형식이 올바르지 않다")

    def post_comment(self, repo, pr, body, delivery_id):
        """PR에 코멘트를 게시하고 URL을 돌려준다. 같은 delivery_id는 한 번만 게시된다."""
        data = self._post("/api/comment", {"repo": repo, "pr": pr, "body": body, "deliveryId": delivery_id})
        url = data.get("url") if isinstance(data, dict) else None
        if not isinstance(url, str):
            raise GithubAppError("github-app 응답 형식이 올바르지 않다")
        return url
