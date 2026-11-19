"""분석 명령. 사용법: testgate run --request <요청 파일> --context <맥락 파일>

요청 파일과 결과의 모양은 contracts/의 request.v1, result.v1 이다(원본은 hermes-controller).
요청 파일의 코멘트 원문을 /qa 문법으로 읽고, github-app에서 PR 맥락을 가져와 분석하고,
보고서를 파일로 저장하고, github-app을 통해 PR에 코멘트한다. 맥락 파일(context.v1)이 있으면 용어집으로 붙인다.
끝나면 표준 출력의 마지막 줄에 결과 JSON 한 줄을 낸다. 본 프로젝트는 Hermes를 모른다.
"""

import json
import logging
import os
import pathlib
import re
import sys
import time

from testgate import analyze as analyze_mod
from testgate import budget, config, contextfile, diffsource, githubapp, knowledge, ledger, prompt, qa, report, runner

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


REQUEST_VERSION = 1
TARGETS = {"pull_request": None, "issue": "issue", "pull_request_review": "pull_request_review"}
MAX_REQUEST_BYTES = 1024 * 1024


def load_request(path, allowed_owners):
    """요청 파일(request.v1)을 읽고 값을 다시 검증한다. 파일은 신뢰하지 않는다.

    /qa 명령이 아니면 None을 돌려준다(할 일이 없다). 문제가 있으면 RunError.
    """
    try:
        raw = pathlib.Path(path).read_bytes()[: MAX_REQUEST_BYTES + 1]
        data = json.loads(raw.decode("utf-8")) if len(raw) <= MAX_REQUEST_BYTES else None
    except (OSError, ValueError):
        raise RunError("요청 파일을 읽을 수 없다")
    if not isinstance(data, dict) or data.get("version") != REQUEST_VERSION:
        raise RunError("요청 파일의 형식이 올바르지 않다")
    delivery_id, repo, pr, target, body = (data.get(k) for k in ("deliveryId", "repo", "pr", "target", "body"))
    if not isinstance(delivery_id, str) or not DELIVERY_ID_PATTERN.match(delivery_id) or set(delivery_id) == {"."}:
        raise RunError("요청의 deliveryId가 올바르지 않다")
    if not isinstance(repo, str) or not REPO_PATTERN.match(repo):
        raise RunError("요청의 repo가 올바르지 않다")
    if repo.split("/")[0] not in allowed_owners:
        raise RunError("허용되지 않은 레포 소유자다")
    if not isinstance(pr, int) or isinstance(pr, bool) or pr < 1:
        raise RunError("요청의 pr가 올바르지 않다")
    if target not in TARGETS:
        raise RunError("요청의 target이 올바르지 않다")
    if not isinstance(body, str):
        raise RunError("요청의 body가 올바르지 않다")
    parsed = qa.parse_qa(body)
    if parsed is None:
        return None
    unsupported = TARGETS[target]
    author = data.get("author")
    if not isinstance(author, str) or not LOGIN_PATTERN.match(author):
        author = None  # 멘션에 쓰므로 GitHub 로그인 형식이 아니면 버린다
    return {"deliveryId": delivery_id, "repo": repo, "pr": pr,
            "commit": None if unsupported else parsed["commit"],
            "text": "" if unsupported else parsed["text"],
            "free": False if unsupported else parsed["free"],
            "unsupported": unsupported, "author": author}


def cleanup(home, retention_days, now=time.time):
    """보관 기간이 지난 보고서와 기록 파일을 지운다. 요청 파일은 controller가 관리한다."""
    cutoff = now() - retention_days * 86400
    for sub in ("reports", "threads"):
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


def _guide(request, settings, app):
    """지원하지 않는 위치의 /qa 에는 분석하지 않고 안내만 단다. Claude도 기록도 쓰지 않는다."""
    kind = request["unsupported"]
    label = "이슈" if kind == "issue" else "PR"
    name = f"[{label}{request['pr']} - 안내]"
    summary = {"result": "ok", "verdict": "-", "mode": "guide", "session": name, "report": "-", "comment": "skipped"}
    markdown = f"{UNSUPPORTED_GUIDANCE[kind]}\n\n---\n세션: `{name}`\n"
    if settings["post_comments"]:
        try:
            summary["comment"] = app.post_comment(request["repo"], request["pr"], markdown, request["deliveryId"])
        except Exception as exc:  # noqa: BLE001 - 안내 실패가 분석 명령을 죽이면 안 된다
            log.exception("안내 코멘트 게시 실패 id=%r", request["deliveryId"])
            summary["comment"] = "failed"
            summary["error"] = _short_error(exc)
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


def execute(request_path, context_path, home, settings, allowed_owners, claude, app):
    """분석 전체를 실행하고 요약 사전을 돌려준다. 오류는 요약의 result=failed 로 나타낸다.
    /qa 명령이 아닌 요청은 result=ignored 이다.

    예상 밖 예외도 여기서 잡는다. 잡지 않으면 PR에 아무 흔적 없이 사라지고 기록은 pending으로 남는다.
    """
    summary = {"result": "failed", "verdict": "-", "mode": "-", "session": "-", "report": "-", "comment": "skipped"}
    try:
        cleanup(home, settings["retention_days"])
    except Exception:  # noqa: BLE001 - 정리 실패가 분석을 막으면 안 된다
        log.exception("오래된 파일 정리 중 오류")
    try:
        request = load_request(request_path, allowed_owners)
    except RunError as exc:
        log.warning("요청을 처리하지 않음: %s", exc)
        summary["error"] = str(exc)
        return summary
    if request is None:
        log.info("/qa 명령이 아니어서 할 일이 없음")
        return dict(summary, result="ignored")
    delivery_id = request["deliveryId"]
    log.info("시작 id=%r", delivery_id)

    if request["unsupported"]:
        return _guide(request, settings, app)

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
        # 맥락 파일(context.v1)이 있으면 용어집으로 읽는다. 없으면 아무 일도 없다.
        if context_path:
            kb = knowledge.CompositeKnowledge([kb, contextfile.ContextFileKnowledge(context_path)])
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
    return summary


def _record(home, repo, pr, delivery_id, record, title):
    """PR 대화 기록에 결과를 남긴다. 실패해도 분석 결과에는 영향이 없다."""
    try:
        ledger.finalize(home, repo, pr, delivery_id, record, title=title)
    except Exception:  # noqa: BLE001
        log.exception("PR 기록 저장 실패 id=%r", delivery_id)


RESULT_STATUS = {"ok": "done", "failed": "failed", "ignored": "ignored"}


def result_line(summary):
    """controller가 읽는 결과 한 줄(result.v1). 세션 이름은 코드가 만든 값이다. 사용자 입력은 넣지 않는다."""
    name = summary.get("session")
    return json.dumps({"version": 1, "status": RESULT_STATUS.get(summary.get("result"), "failed"),
                       "session_name": name if name and name != "-" else None}, ensure_ascii=False)


SECRET_ENV = "TESTGATE_GITHUB_APP_SECRET"


def load_app(settings, environ=None):
    """github-app 클라이언트. 서명 키는 환경 변수에서만 읽는다.

    이 프로젝트는 비밀을 보관하거나 파일에서 읽지 않는다. 값은 실행 환경이 넘긴다(.env.example에 이름이 있다).
    """
    environ = os.environ if environ is None else environ
    secret = environ.get(SECRET_ENV, "")
    if not secret:
        raise githubapp.GithubAppError(f"환경 변수 {SECRET_ENV}이 설정되어 있지 않다")
    return githubapp.GithubApp(settings["github_app_url"], secret)


def _setup_logging():
    """표준 오류로 시간표를 붙여 기록한다. bin/testgate-run 이 이것을 로그 파일로 보낸다. 표준 출력은 결과 한 줄만 쓴다."""
    logging.basicConfig(level=logging.INFO, stream=sys.stderr, format="%(asctime)s %(levelname)s %(message)s")


def main(request_path, context_path):
    _setup_logging()
    failed = {"result": "failed", "session": "-"}
    try:
        home = config.hermes_home()
        settings = config.load_analysis_config()
        allowed = config.load_allowed_owners()
        try:
            app = load_app(settings)
        except githubapp.GithubAppError as exc:
            log.error("github-app 클라이언트를 만들 수 없음: %s", exc)
            print(result_line(failed))
            return 1
        claude = runner.ClaudeRunner(
            binary=settings["claude_binary"], model=settings["claude_model"],
            timeout=settings["timeout_seconds"], effort=settings["claude_effort"],
        )
        summary = execute(request_path, context_path, home, settings, allowed, claude, app)
    except Exception:  # noqa: BLE001 - 마지막 방어선. 호출한 쪽이 알 수 있게 로그와 결과를 남긴다
        log.exception("예상 밖 오류로 중단됨")
        print(result_line(failed))
        return 1
    log.info("끝 result=%s verdict=%s mode=%s comment=%s report=%s", summary["result"], summary["verdict"], summary["mode"],
             summary["comment"], summary["report"])
    print(result_line(summary))
    return 0 if summary["result"] in ("ok", "ignored") else 1
