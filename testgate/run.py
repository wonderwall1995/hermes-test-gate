"""Hermes 세션이 실행하는 래퍼. 인자는 delivery ID 하나뿐이다.

요청 파일(필터가 저장)을 읽고, github-app에서 PR 맥락을 가져와 분석하고,
보고서를 파일로 저장하고, github-app을 통해 PR에 코멘트하고, 세션 이름을 바꾼다.
세션의 LLM이 읽는 표준 출력에는 고정된 형식의 짧은 요약만 쓴다. QA 서술이나 diff는 쓰지 않는다.
"""

import json
import logging
import os
import pathlib
import re
import shutil
import sqlite3
import subprocess
import sys
import time

from testgate import analyze as analyze_mod
from testgate import budget, config, diffsource, githubapp, knowledge, ledger, prompt, report, runner

DELIVERY_ID_PATTERN = re.compile(r"^[A-Za-z0-9._-]{1,100}$")
REPO_PATTERN = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")
COMMIT_PATTERN = re.compile(r"^[0-9a-f]{7,40}$")
LOGIN_PATTERN = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9-]{0,38})$")
log = logging.getLogger("testgate")

UNSUPPORTED_GUIDANCE = {
    "issue": "이슈 코멘트의 `/qa`는 지원하지 않습니다. 분석은 Pull Request의 대화창(Conversation)에 쓴 코멘트에서만 합니다.",
    "pull_request_review": "코드 줄에 단 리뷰 코멘트의 `/qa`는 지원하지 않습니다. Pull Request의 대화창(Conversation)에 일반 코멘트로 다시 써 주세요.",
}
FAILURE_COMMENT = "분석에 실패했습니다. 잠시 뒤 같은 요청을 다시 코멘트로 남겨 주세요."
ACK_COMMENT = ("분석을 시작했습니다. 보통 1~2분 걸리며, 끝나면 이 코멘트를 결과로 바꾸고 알려 드립니다.\n\n"
               "---\n세션: `{name}`\n")
FALLBACK_NOTICE = "결과는 아래 새 코멘트에 올렸습니다."
EMPTY_FREE_ANSWER = "질문 내용이 없습니다. `/qa free: 질문`처럼 콜론 뒤에 내용을 적어 주세요."


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
    free = data.get("free", False)
    if not isinstance(free, bool):
        raise RunError("요청의 free가 올바르지 않다")
    unsupported = data.get("unsupported")
    if unsupported is not None and unsupported not in UNSUPPORTED_GUIDANCE:
        raise RunError("요청의 unsupported가 올바르지 않다")
    author = data.get("author")
    if not isinstance(author, str) or not LOGIN_PATTERN.match(author):
        author = None  # 멘션에 쓰므로 GitHub 로그인 형식이 아니면 버린다
    return {"deliveryId": delivery_id, "repo": repo, "pr": pr, "commit": commit, "text": text, "free": free,
            "unsupported": unsupported, "author": author}


def cleanup(home, retention_days, now=time.time):
    """보관 기간이 지난 요청과 보고서 파일을 지운다."""
    cutoff = now() - retention_days * 86400
    for sub in ("requests", "reports", "threads"):
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


def find_session_id(home, route, delivery_id):
    """이 요청의 Hermes 세션 ID를 상태 DB에서 chat_id로 찾는다.

    환경 변수 HERMES_SESSION_ID는 쓰지 않는다. 게이트웨이가 프로세스 전체에 마지막 세션의 값을 덮어쓰므로
    세션 밖에서 실행되는 래퍼는 엉뚱한 세션의 이름을 바꿀 수 있다.
    """
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


def wait_for_session(home, route, delivery_id, tries=20, delay=1.0, sleep=time.sleep):
    """세션 행이 생길 때까지 기다린다. 래퍼는 세션보다 먼저 시작되므로 빨리 끝나는 요청에서는 아직 없을 수 있다."""
    for attempt in range(tries):
        session_id = find_session_id(home, route, delivery_id)
        if session_id:
            return session_id
        if attempt + 1 < tries:
            sleep(delay)
    return None


def rename_session(home, route, delivery_id, name, hermes_binary, run=subprocess.run, sleep=time.sleep):
    """세션 이름을 바꾼다. 실패해도 분석 결과에는 영향이 없으며 이유만 돌려준다."""
    session_id = wait_for_session(home, route, delivery_id, sleep=sleep)
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


def _guide(request, settings, app, home, hermes_run, sleep):
    """지원하지 않는 위치의 /qa 에는 분석하지 않고 안내만 단다. Claude도 기록도 쓰지 않는다."""
    kind = request["unsupported"]
    label = "이슈" if kind == "issue" else "PR"
    name = f"[{label}{request['pr']} - 안내]"
    summary = {"result": "ok", "verdict": "-", "mode": "guide", "session": name, "report": "-", "comment": "skipped", "rename": "skipped"}
    markdown = f"{UNSUPPORTED_GUIDANCE[kind]}\n\n---\n세션: `{name}`\n"
    if settings["post_comments"]:
        try:
            summary["comment"] = app.post_comment(request["repo"], request["pr"], markdown, request["deliveryId"])
        except Exception as exc:  # noqa: BLE001 - 안내 실패가 래퍼를 죽이면 안 된다
            log.exception("안내 코멘트 게시 실패 id=%r", request["deliveryId"])
            summary["comment"] = "failed"
            summary["error"] = _short_error(exc)
    summary["rename"] = _rename(home, settings, request["deliveryId"], name, hermes_run, sleep)
    return summary


def _post_ack(request, settings, app, name):
    """분석 시작 직후 "분석 중" 코멘트를 먼저 게시하고 코멘트 id를 돌려준다. 실패하면 None이고 분석은 계속한다."""
    if not settings["post_comments"]:
        return None
    try:
        _, comment_id = app.post_comment_ref(request["repo"], request["pr"], ACK_COMMENT.format(name=name),
                                             f"{request['deliveryId']}-ack")
        return comment_id
    except Exception:  # noqa: BLE001 - 확인 코멘트 실패가 분석을 막으면 안 된다
        log.exception("확인 코멘트 게시 실패 id=%r", request["deliveryId"])
        return None


MAX_UPLOAD_BYTES = 900000   # github-app 의 본문 크기 한도(1MB)보다 작게 둔다


def _with_report_link(markdown, outcome, request, settings, app):
    """설정이 켜져 있으면 HTML 보고서를 보관소에 올리고 내려받는 링크를 코멘트에 붙인다. 실패해도 분석 결과는 그대로 올린다."""
    html = outcome.get("html")
    if not html or outcome["mode"] == "free":
        return markdown
    if len(html.encode("utf-8")) > MAX_UPLOAD_BYTES:
        log.warning("HTML 보고서가 커서 올리지 않음 id=%r", request["deliveryId"])
        return markdown
    try:
        url = app.upload_report(request["repo"], request["pr"], html, request["deliveryId"])
    except Exception:  # noqa: BLE001 - 링크가 없어도 코멘트는 올린다
        log.exception("HTML 보고서 업로드 실패 id=%r", request["deliveryId"])
        return markdown
    # 코멘트의 맨 아래에 "HTML 보고서" 헤더를 두고 받기 링크를 둔다.
    return f"{markdown.rstrip()}\n\n# HTML 보고서\n\n[HTML 보고서 받기]({url}) (HTML 파일, 7일간 받을 수 있음)\n"


def _with_mention(request, settings, markdown):
    login = request.get("author")
    if settings["mention_requester"] and login:
        return f"@{login}\n\n{markdown}"
    return markdown


def _deliver(request, settings, app, markdown, comment_id, ack, summary):
    """결과를 확인 코멘트에 싣는다. 수정할 수 없으면 새 코멘트로 올리고 확인 코멘트에는 그 사실을 적는다."""
    repo, pr = request["repo"], request["pr"]
    body = _with_mention(request, settings, markdown)
    try:
        if ack is not None:
            try:
                summary["comment"] = app.update_comment(repo, pr, ack, body)
                _notify_new_comment(request, settings, app, summary)
                return
            except Exception:  # noqa: BLE001 - 수정 실패 시 새 코멘트로 올린다
                log.exception("확인 코멘트 수정 실패 id=%r", request["deliveryId"])
        summary["comment"] = app.post_comment(repo, pr, body, comment_id)
        if ack is not None:
            try:
                app.update_comment(repo, pr, ack, FALLBACK_NOTICE)
            except Exception:  # noqa: BLE001
                log.exception("확인 코멘트 안내 수정 실패 id=%r", request["deliveryId"])
    except Exception as exc:  # noqa: BLE001
        log.exception("코멘트 게시 실패 id=%r", request["deliveryId"])
        summary["comment"] = "failed"
        summary.setdefault("error", _short_error(exc))


def _notify_new_comment(request, settings, app, summary):
    """설정이 켜져 있으면 수정으로는 알림이 가지 않는 경우를 위해 짧은 새 코멘트를 추가로 올린다."""
    login = request.get("author")
    if not (settings["notify_with_new_comment"] and login):
        return
    try:
        app.post_comment(request["repo"], request["pr"], f"@{login} 결과가 준비되었습니다: {summary['comment']}",
                         f"{request['deliveryId']}-notify")
    except Exception:  # noqa: BLE001
        log.exception("알림 코멘트 게시 실패 id=%r", request["deliveryId"])


def _short_error(exc):
    """요약에 넣는 오류 문구. 알려진 오류는 메시지를, 예상 밖 오류는 종류만 쓴다."""
    known = (diffsource.DiffSourceError, prompt.PromptError, runner.RunnerError, analyze_mod.AnalysisError, RunError)
    return str(exc)[:200] if isinstance(exc, known) else f"unexpected:{type(exc).__name__}"


def _rename(home, settings, delivery_id, name, hermes_run, sleep):
    try:
        return rename_session(home, settings["route_name"], delivery_id, name, settings["hermes_binary"], hermes_run, sleep)
    except Exception:  # noqa: BLE001
        log.exception("세션 이름 변경 중 오류 id=%r", delivery_id)
        return "failed"


def execute(delivery_id, home, settings, allowed_owners, claude, app, hermes_run=subprocess.run, sleep=time.sleep):
    """분석 전체를 실행하고 요약 사전을 돌려준다. 오류는 요약의 result=failed 로 나타낸다.

    예상 밖 예외도 여기서 잡는다. 잡지 않으면 PR에 아무 흔적 없이 사라지고 기록은 pending으로 남는다.
    """
    summary = {"result": "failed", "verdict": "-", "mode": "-", "session": "-", "report": "-", "comment": "skipped", "rename": "skipped"}
    try:
        cleanup(home, settings["retention_days"])
    except Exception:  # noqa: BLE001 - 정리 실패가 분석을 막으면 안 된다
        log.exception("오래된 파일 정리 중 오류")
    try:
        request = load_request(home, delivery_id, allowed_owners)
    except RunError as exc:
        log.warning("요청을 처리하지 않음 id=%r: %s", delivery_id, exc)
        summary["error"] = str(exc)
        return summary

    if request["unsupported"]:
        return _guide(request, settings, app, home, hermes_run, sleep)

    repo, pr, commit = request["repo"], request["pr"], request["commit"]
    # 같은 PR의 요청 순번. 기록을 쓸 수 없어도 분석은 계속한다.
    try:
        seq = ledger.reserve(home, repo, pr, delivery_id)
    except OSError:
        log.exception("순번 예약 실패 id=%r", delivery_id)
        seq = None
    name = report.session_name(pr, None, commit, seq)
    summary["session"] = name
    reports = data_dir(home) / "reports"
    ack = _post_ack(request, settings, app, name)
    context = None
    outcome = None
    try:
        context = app.fetch_context(repo, pr, commit, select=lambda files: budget.paths_to_fetch(files, settings))
        context = budget.apply(context, settings)
        name = report.session_name(pr, context["title"], commit, seq)
        summary["session"] = name
        try:
            history = [e for e in ledger.done_entries(home, repo, pr) if e.get("deliveryId") != delivery_id]
        except OSError:
            history = []
        kb = knowledge.DirectoryKnowledge(settings["knowledge_dirs"]) if settings["knowledge_dirs"] else knowledge.NullKnowledge()
        if request["free"] and not request["text"].strip():
            # 질문이 비어 있으면 Claude를 부르지 않고 안내만 한다.
            outcome = {"markdown": report.render_free(EMPTY_FREE_ANSWER, name), "verdict": "-", "mode": "free",
                       "notes": [], "result": {"answer": EMPTY_FREE_ANSWER}, "meta": {}, "files_record": {},
                       "summary": "", "answer": EMPTY_FREE_ANSWER, "session_name": name}
        elif request["free"]:
            outcome = analyze_mod.analyze_free(request, context, kb, claude, history=history, name=name, rules_settings=settings)
        else:
            outcome = analyze_mod.analyze(request, context, kb, claude, history=history, name=name)
    except (diffsource.DiffSourceError, prompt.PromptError, runner.RunnerError, analyze_mod.AnalysisError) as exc:
        log.warning("분석 실패 id=%r: %s", delivery_id, exc)
        summary["error"] = str(exc)[:200]
        outcome = None
    except Exception as exc:  # noqa: BLE001 - 예상 밖 오류. 실패 코멘트를 남기고 로그에 자세히 기록한다
        log.exception("예상 밖 오류 id=%r", delivery_id)
        summary["error"] = _short_error(exc)
        outcome = None

    if outcome is None:
        markdown = f"{FAILURE_COMMENT}\n\n---\n세션: `{name}`\n"
        comment_id = f"{delivery_id}-failed"
        _record(home, repo, pr, delivery_id, {"status": "failed", "session": name, "error": summary.get("error", "")},
                context and context.get("title"))
    else:
        markdown = outcome["markdown"]
        comment_id = delivery_id
        if settings["upload_report"] and settings["post_comments"]:
            markdown = _with_report_link(markdown, outcome, request, settings, app)
        summary.update(result="ok", verdict=outcome["verdict"], mode=outcome["mode"])
        meta = outcome.get("meta") or {}
        log.info("사용량 id=%r prompt_chars=%s answer_chars=%s tokens=%s cost_usd=%s duration_ms=%s", delivery_id,
                 outcome.get("prompt_chars"), len(outcome["markdown"]), meta.get("usage"), meta.get("cost_usd"),
                 meta.get("duration_ms"))
        # 보고서 파일 저장이 실패해도 결과는 코멘트로 전달한다.
        try:
            write_private(reports / f"{delivery_id}.md", markdown)
            if outcome.get("html"):
                write_private(reports / f"{delivery_id}.html", outcome["html"])
            write_private(reports / f"{delivery_id}.json", json.dumps(
                {"request": {k: request[k] for k in ("deliveryId", "repo", "pr", "commit", "free")}, "session": name,
                 "result": outcome["result"], "notes": outcome["notes"], "meta": outcome["meta"]}, ensure_ascii=False, indent=2))
            # 경로를 출력하면 Hermes가 파일 첨부로 오해해 전송하려 한다. 저장 여부만 알린다.
            summary["report"] = "saved"
        except OSError:
            log.exception("보고서 저장 실패 id=%r", delivery_id)
            summary["report"] = "not-saved"
        record = {"status": "done", "kind": outcome["mode"], "session": name, "commit": commit,
                  "scope": context["scope"], "head_sha": context["head_sha"], "title": context["title"],
                  "summary": outcome["summary"][:600], "files": outcome["files_record"]}
        if outcome["mode"] == "free":
            record["question"] = request["text"][:500]
            record["answer"] = outcome["answer"][:1500]
        _record(home, repo, pr, delivery_id, record, context["title"])

    if settings["post_comments"]:
        _deliver(request, settings, app, markdown, comment_id, ack, summary)
    summary["rename"] = _rename(home, settings, delivery_id, name, hermes_run, sleep)
    return summary


def _record(home, repo, pr, delivery_id, record, title):
    """PR 대화 기록에 결과를 남긴다. 실패해도 분석 결과에는 영향이 없다."""
    try:
        ledger.finalize(home, repo, pr, delivery_id, record, title=title)
    except Exception:  # noqa: BLE001
        log.exception("PR 기록 저장 실패 id=%r", delivery_id)


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


def _setup_logging():
    """표준 오류로 시간표를 붙여 기록한다. 래퍼 스크립트(testgate-run)가 이것을 $HERMES_HOME/logs/testgate.log 로 보낸다."""
    logging.basicConfig(level=logging.INFO, stream=sys.stderr, format="%(asctime)s %(levelname)s %(message)s")


def main(delivery_id):
    _setup_logging()
    log.info("시작 id=%r", delivery_id)
    failed = {"result": "failed", "verdict": "-", "mode": "-", "session": "-", "report": "-", "comment": "skipped", "rename": "skipped"}
    try:
        home = config.hermes_home()
        settings = config.load_analysis_config()
        allowed = config.load_allowed_owners()
        try:
            app = load_app(settings)
        except githubapp.GithubAppError as exc:
            log.error("github-app 클라이언트를 만들 수 없음: %s", exc)
            print(format_summary(dict(failed, error=str(exc))))
            return 1
        claude = runner.ClaudeRunner(
            binary=settings["claude_binary"], model=settings["claude_model"],
            timeout=settings["timeout_seconds"], effort=settings["claude_effort"],
        )
        summary = execute(delivery_id, home, settings, allowed, claude, app)
    except Exception as exc:  # noqa: BLE001 - 마지막 방어선. 호출한 쪽이 알 수 있게 로그와 요약을 남긴다
        log.exception("래퍼가 예상 밖 오류로 중단됨 id=%r", delivery_id)
        print(format_summary(dict(failed, error=_short_error(exc))))
        return 1
    print(format_summary(summary))
    log.info("끝 id=%r %s", delivery_id, format_summary(summary))
    return 0 if summary["result"] == "ok" else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1]) if len(sys.argv) > 1 else 2)
