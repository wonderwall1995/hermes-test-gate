"""PR 맥락(제목, 설명, 변경 파일, diff)을 공급하는 소스."""

import re
import subprocess

# git 인자로 쓸 수 있는 이름. 앞의 '-'는 옵션으로 해석되므로 금지한다.
REF_PATTERN = re.compile(r"^[A-Za-z0-9_][A-Za-z0-9._/@~^-]*$")


class DiffSourceError(Exception):
    pass


def check_ref(name):
    if not isinstance(name, str) or not REF_PATTERN.match(name) or ".." in name:
        raise DiffSourceError(f"허용되지 않는 git 참조 이름: {name!r}")
    return name


def split_diff_by_file(diff_text):
    """'diff --git' 단위로 나눈 {경로: 블록} 목록을 순서대로 반환한다."""
    blocks = []
    current = []
    for line in diff_text.splitlines(keepends=True):
        if line.startswith("diff --git ") and current:
            blocks.append("".join(current))
            current = []
        current.append(line)
    if current:
        blocks.append("".join(current))
    return blocks


def blocks_by_path(diff_text):
    """'diff --git a/x b/y' 블록을 새 경로(b/ 쪽)로 찾을 수 있게 한다."""
    result = {}
    for block in split_diff_by_file(diff_text):
        header = block.split("\n", 1)[0]
        match = re.match(r"^diff --git a/.+? b/(.+)$", header)
        if match:
            result[match.group(1)] = block
    return result


def apply_limit(context, max_chars):
    """호환용 얇은 함수. 예산 배분은 testgate.budget.apply 가 한다 (순환 참조를 피하려고 늦게 가져온다)."""
    from testgate import budget
    return budget.apply(context, {"max_diff_chars": max_chars})


class LocalGitSource:
    """로컬 git 저장소에서 diff를 만든다. 개발과 시험에 쓴다."""

    def __init__(self, repo_path):
        self.repo_path = repo_path

    def _git(self, *args):
        result = subprocess.run(
            ["git", "-C", self.repo_path, *args],
            capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=60,
        )
        if result.returncode != 0:
            raise DiffSourceError(f"git 실패: {' '.join(args[:2])}: {result.stderr.strip()[:200]}")
        return result.stdout

    def get(self, base_ref, head_ref, commit=None, title="", body=""):
        check_ref(base_ref)
        check_ref(head_ref)
        if commit:
            check_ref(commit)
            spec = [f"{commit}^", commit]
            scope = "commit"
        else:
            spec = [f"{base_ref}...{head_ref}"]
            scope = "pr"
        head_sha = self._git("rev-parse", commit or head_ref).strip()

        numstat = self._git("diff", "--numstat", "--no-renames", *spec)
        files = []
        for line in numstat.splitlines():
            added, deleted, path = line.split("\t", 2)
            files.append({
                "path": path,
                "status": "modified",
                "additions": 0 if added == "-" else int(added),
                "deletions": 0 if deleted == "-" else int(deleted),
                "diff_included": True,
            })
        # 크기 제한은 여기서 하지 않는다. 예산 배분은 budget.apply 가 한다.
        diff = self._git("diff", "--no-renames", "--no-color", *spec)
        return {
            "title": title,
            "body": body,
            "base_ref": base_ref,
            "head_sha": head_sha,
            "scope": scope,
            "commit": commit,
            "files": files,
            "diff": diff,
            "truncated": False,
        }
