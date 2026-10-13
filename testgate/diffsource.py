"""PR 맥락(제목, 설명, 변경 파일, diff)을 공급하는 소스."""

import re
import subprocess

MAX_DIFF_CHARS = 120000
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


def limit_diff(files, blocks, max_chars):
    """상한 안에서 앞쪽 블록부터 담는다. 담지 못한 파일은 diff_included=False로 표시한다."""
    total = 0
    kept = []
    truncated = False
    for index, block in enumerate(blocks):
        if total + len(block) > max_chars:
            truncated = True
            for later in range(index, len(files)):
                files[later]["diff_included"] = False
            break
        kept.append(block)
        total += len(block)
        if index < len(files):
            files[index]["diff_included"] = True
    return "".join(kept), truncated


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
    """이미 만들어진 맥락의 diff를 다시 줄인다. 파일 순서대로 담고 못 담은 파일은 diff_included=False이다."""
    blocks = blocks_by_path(context["diff"])
    total = 0
    kept = []
    truncated = context["truncated"]
    files = []
    for f in context["files"]:
        f = dict(f)
        block = blocks.get(f["path"])
        if block is None or not f.get("diff_included", True):
            f["diff_included"] = False
            truncated = True
        elif total + len(block) > max_chars:
            f["diff_included"] = False
            truncated = True
        else:
            kept.append(block)
            total += len(block)
        files.append(f)
    return dict(context, files=files, diff="".join(kept), truncated=truncated)


class LocalGitSource:
    """로컬 git 저장소에서 diff를 만든다. 개발과 시험에 쓴다."""

    def __init__(self, repo_path, max_diff_chars=MAX_DIFF_CHARS):
        self.repo_path = repo_path
        self.max_diff_chars = max_diff_chars

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
        raw = self._git("diff", "--no-renames", "--no-color", *spec)
        blocks = split_diff_by_file(raw)
        diff, truncated = limit_diff(files, blocks, self.max_diff_chars)
        return {
            "title": title,
            "body": body,
            "base_ref": base_ref,
            "head_sha": head_sha,
            "scope": scope,
            "files": files,
            "diff": diff,
            "truncated": truncated,
        }
