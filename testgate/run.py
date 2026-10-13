"""Hermes 세션이 실행하는 래퍼. 인자는 delivery ID 하나뿐이다.

요청 파일(필터가 저장)을 읽고, github-app에서 PR 맥락을 가져와 분석하고,
보고서를 파일로 저장하고, github-app을 통해 PR에 코멘트하고, 세션 이름을 바꾼다.
세션의 LLM이 읽는 표준 출력에는 고정된 형식의 짧은 요약만 쓴다. QA 서술이나 diff는 쓰지 않는다.
"""

import json
import os
import pathlib
import re
import shutil
import sqlite3
import subprocess
import sys
import time

from testgate import analyze as analyze_mod
from testgate import config, diffsource, githubapp, knowledge, prompt, report, runner

DELIVERY_ID_PATTERN = re.compile(r"^[A-Za-z0-9._-]{1,100}$")
REPO_PATTERN = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")
COMMIT_PATTERN = re.compile(r"^[0-9a-f]{7,40}$")
FAILURE_COMMENT = "분석에 실패했습니다. 잠시 뒤 같은 요청을 다시 코멘트로 남겨 주세요."


class RunError(Exception):
    pass


def data_dir(home):
    return pathlib.Path(home) / "testgate"


def load_request(home, delivery_id, allowed_owners):
    """요청 파일을 읽고 값을 다시 검증한다. 파일은 신뢰하지 않는다."""
    if not DELIVERY_ID_PATTERN.match(delivery_id):
        raise RunError("delivery ID 형식이 올바르지 않다")
    path = data_dir(home) / "requests" / f"{delivery_id}.json"
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        raise RunError("요청 파일을 읽을 수 없다")
    repo, pr, commit, text = data.get("repo"), data.get("pr"), data.get("commit"), data.get("text")
    if not isinstance(repo, str) or not REPO_PATTERN.match(repo):
        raise RunError("요청의 repo가 올바르지 않다")
    if repo.split("/")[0] not in allowed_owners:
        raise RunError("허용되지 않은 레포 소유자다")
    if not isinstance(pr, int) or isinstance(pr, bool) or pr < 1:
        raise RunError("요청의 pr가 올바르지 않다")
    if commit is not None and (not isinstance(commit, str) or not COMMIT_PATTERN.match(commit)):
        raise RunError("요청의 commit이 올바르지 않다")
    if not isinstance(text, str):
        raise RunError("요청의 text가 올바르지 않다")
    return {"deliveryId": delivery_id, "repo": repo, "pr": pr, "commit": commit, "text": text}


def cleanup(home, retention_days, now=time.time):
    """보관 기간이 지난 요청과 보고서 파일을 지운다."""
    cutoff = now() - retention_days * 86400
    for sub in ("requests", "reports"):
        folder = data_dir(home) / sub
        if not folder.is_dir():
            continue
        for item in folder.iterdir():
            try:
                if item.is_file() and item.stat().st_mtime < cutoff:
                    item.unlink()
            except OSError:
                pass


def write_private(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as handle:
        handle.write(text)


def find_session_id(home, route, delivery_id, env):
    """이 요청의 Hermes 세션 ID. 환경 변수가 있으면 그것을, 없으면 상태 DB에서 chat_id로 찾는다."""
    from_env = env.get("HERMES_SESSION_ID")
    if from_env and re.match(r"^[A-Za-z0-9_.-]+$", from_env):
        return from_env
    db = pathlib.Path(home) / "state.db"
    try:
        conn = sqlite3.connect(f"file:{db}?mode=ro", uri=True, timeout=5)
        try:
            row = conn.execute(
                "select id from sessions where chat_id = ? order by started_at desc limit 1",
                (f"webhook:{route}:{delivery_id}",),
            ).fetchone()
        finally:
            conn.close()
    except sqlite3.Error:
        return None
    return row[0] if row else None


def rename_session(home, route, delivery_id, name, hermes_binary, env=None, run=subprocess.run):
    """세션 이름을 바꾼다. 실패해도 분석 결과에는 영향이 없으며 이유만 돌려준다."""
    env = os.environ if env is None else env
    session_id = find_session_id(home, route, delivery_id, env)
    if not session_id:
        return "skipped:no_session"
    binary = shutil.which(hermes_binary) or (hermes_binary if os.path.isabs(hermes_binary) and os.access(hermes_binary, os.X_OK) else None)
    if not binary:
        return "skipped:no_hermes_binary"
    try:
        result = run([binary, "sessions", "rename", session_id, name], capture_output=True, text=True, timeout=30)
    except (OSError, subprocess.TimeoutExpired):
        return "failed"
    return "renamed" if result.returncode == 0 else "failed"


def execute(delivery_id, home, settings, allowed_owners, claude, app, env=None, hermes_run=subprocess.run):
    """분석 전체를 실행하고 요약 사전을 돌려준다. 오류는 요약의 result=failed 로 나타낸다."""
    summary = {"result": "failed", "verdict": "-", "mode": "-", "session": "-", "report": "-", "comment": "skipped", "rename": "skipped"}
    cleanup(home, settings["retention_days"])
    try:
        request = load_request(home, delivery_id, allowed_owners)
    except RunError as exc:
        summary["error"] = str(exc)
        return summary

    name = report.session_name(request["pr"], request["commit"])
    summary["session"] = name
    reports = data_dir(home) / "reports"
    try:
        context = app.fetch_context(request["repo"], request["pr"], request["commit"])
        context = diffsource.apply_limit(context, settings["max_diff_chars"])
        kb = knowledge.DirectoryKnowledge(settings["knowledge_dirs"]) if settings["knowledge_dirs"] else knowledge.NullKnowledge()
        outcome = analyze_mod.analyze(request, context, kb, claude)
    except (diffsource.DiffSourceError, prompt.PromptError, runner.RunnerError, analyze_mod.AnalysisError) as exc:
        summary["error"] = str(exc)[:200]
        outcome = None

    if outcome is None:
        markdown = f"{FAILURE_COMMENT}\n\n---\n세션: `{name}`\n"
        comment_id = f"{delivery_id}-failed"
    else:
        markdown = outcome["markdown"]
        comment_id = delivery_id
        summary.update(result="ok", verdict=outcome["verdict"], mode=outcome["mode"])
        write_private(reports / f"{delivery_id}.md", markdown)
        write_private(reports / f"{delivery_id}.json", json.dumps(
            {"request": {k: request[k] for k in ("deliveryId", "repo", "pr", "commit")}, "result": outcome["result"],
             "notes": outcome["notes"], "meta": outcome["meta"]}, ensure_ascii=False, indent=2))
        # 경로를 출력하면 Hermes가 파일 첨부로 오해해 전송하려 한다. 저장 여부만 알린다.
        summary["report"] = "saved"

    if settings["post_comments"]:
        try:
            summary["comment"] = app.post_comment(request["repo"], request["pr"], markdown, comment_id)
        except diffsource.DiffSourceError as exc:
            summary["comment"] = "failed"
            summary.setdefault("error", str(exc)[:200])
    summary["rename"] = rename_session(home, settings["route_name"], delivery_id, name, settings["hermes_binary"], env, hermes_run)
    return summary


def format_summary(summary):
    """세션 LLM에게 돌아가는 고정 형식의 한 줄. 사용자 입력에서 온 문자열은 넣지 않는다."""
    order = ("result", "verdict", "mode", "session", "report", "comment", "rename")
    parts = [f"{key}={summary[key]}" for key in order]
    if "error" in summary:
        parts.append("error=" + re.sub(r"[^A-Za-z0-9가-힣 _.:/()-]", "?", summary["error"])[:120])
    return " ".join(parts)


SECRET_ENV = "TESTGATE_GITHUB_APP_SECRET"


def load_app(settings, environ=None):
    """github-app 클라이언트. 서명 키는 환경 변수에서만 읽는다.

    이 프로젝트는 비밀을 보관하거나 파일에서 읽지 않는다. 값은 Hermes 실행 환경이 넘긴다 (docs/setup.md 참고).
    """
    environ = os.environ if environ is None else environ
    secret = environ.get(SECRET_ENV, "")
    if not secret:
        raise githubapp.GithubAppError(f"환경 변수 {SECRET_ENV}이 설정되어 있지 않다")
    return githubapp.GithubApp(settings["github_app_url"], secret)


def main(delivery_id):
    home = config.hermes_home()
    settings = config.load_analysis_config()
    allowed = config.load_allowed_owners()
    try:
        app = load_app(settings)
    except githubapp.GithubAppError as exc:
        print(format_summary({"result": "failed", "verdict": "-", "mode": "-", "session": "-", "report": "-",
                              "comment": "skipped", "rename": "skipped", "error": str(exc)}))
        return 1
    claude = runner.ClaudeRunner(
        binary=settings["claude_binary"], model=settings["claude_model"],
        timeout=settings["timeout_seconds"], effort=settings["claude_effort"],
    )
    summary = execute(delivery_id, home, settings, allowed, claude, app)
    print(format_summary(summary))
    return 0 if summary["result"] == "ok" else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1]))
