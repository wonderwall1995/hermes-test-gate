"""Hermes 웹훅 라우트 필터. /qa 코멘트만 통과시킨다.

입력: stdin의 JSON. github-app의 sink가 보낸 {"deliveryId", "event": {...}} 형태이다.
출력: 통과하면 stdout에 JSON 한 개. 버리면 아무것도 출력하지 않고 종료 코드 0으로 끝난다.
이 스크립트는 코멘트 본문을 명령으로 실행하지 않는다. 본문은 비신뢰 입력이다.

코멘트 문법은 두 가지뿐이다.
  /qa [커밋ID] 자유 서술
  /qa 자유 서술
커밋ID는 대괄호 안의 16진수 7~40자이다. 대괄호가 없으면 전부 자유 서술로 본다.
자유 서술은 여러 줄이어도 된다. 대상 브랜치(base)는 코멘트에 쓰지 않는다. PR 정보에서 얻는다.

허용 계정은 이 파일에 쓰지 않는다. 프로젝트 밖의 설정 파일 testgate.json에서 읽는다.
  {"allowed_authors": ["계정"], "allowed_repo_owners": ["계정"]}
설정 파일 찾는 순서: 환경 변수 TESTGATE_CONFIG, 환경 변수 HERMES_HOME, 이 파일이 있는 폴더의 상위 폴더.
설치 위치가 $HERMES_HOME/scripts 이므로 마지막 경로가 $HERMES_HOME 과 같다.
설정 파일이 없거나 잘못되면 모든 요청을 버리고 종료 코드 1로 끝난다 (fail closed).
"""

import json
import os
import pathlib
import re
import sys

COMMAND_PREFIX = "/qa"
MAX_TEXT_CHARS = 10000
# 명령어 바로 뒤에 오는 선택적 커밋ID. 대괄호가 필수이다.
COMMIT_PATTERN = re.compile(r"^\[([0-9a-fA-F]{7,40})\]")


class ConfigError(Exception):
    """설정 파일이 없거나 잘못되었을 때 발생한다."""


def config_path():
    """설정 파일 경로를 반환한다."""
    explicit = os.environ.get("TESTGATE_CONFIG")
    if explicit:
        return pathlib.Path(explicit)
    home = os.environ.get("HERMES_HOME")
    if home:
        return pathlib.Path(home) / "testgate.json"
    return pathlib.Path(__file__).resolve().parent.parent / "testgate.json"


def load_config(path=None):
    """허용 목록을 읽는다. 문제가 있으면 ConfigError를 발생시킨다."""
    path = path or config_path()
    try:
        data = json.loads(pathlib.Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ConfigError(f"설정 파일을 읽을 수 없다: {path} ({exc.__class__.__name__})")
    config = {}
    for key in ("allowed_authors", "allowed_repo_owners"):
        values = data.get(key) if isinstance(data, dict) else None
        if not isinstance(values, list) or not values or not all(isinstance(v, str) and v for v in values):
            raise ConfigError(f"설정 파일의 {key}는 비어 있지 않은 문자열 목록이어야 한다: {path}")
        config[key] = values
    return config


def decide(payload, config):
    """통과하면 변환된 dict를, 버리면 None을 반환한다."""
    if not isinstance(payload, dict):
        return None
    event = payload.get("event")
    if not isinstance(event, dict):
        return None

    # 새로 작성된 코멘트만 받는다. 수정이나 삭제는 분석을 다시 시작하면 안 된다.
    if event.get("kind") != "comment" or event.get("action") != "created":
        return None
    # PR 대화 코멘트만 받는다.
    if event.get("target") != "pull_request":
        return None

    author = event.get("author") or {}
    if author.get("login") not in config["allowed_authors"] or author.get("type") != "User":
        return None
    repo = event.get("repo") or {}
    if repo.get("owner") not in config["allowed_repo_owners"]:
        return None

    body = event.get("body")
    if not isinstance(body, str):
        return None
    parsed = parse_qa(body)
    if parsed is None:
        return None

    return {
        "deliveryId": payload.get("deliveryId"),
        "event": {
            "kind": event.get("kind"),
            "action": event.get("action"),
            "repo": repo,
            "number": event.get("number"),
            "author": author,
            "url": event.get("url"),
            "commentId": event.get("commentId"),
        },
        "qa": parsed,
    }


def parse_qa(body):
    """코멘트 본문에서 /qa 명령을 읽는다. 명령이 아니면 None을 반환한다.

    반환: {"commit": 커밋ID 또는 None, "text": 자유 서술, "truncated": 잘림 여부}
    """
    stripped = body.strip()
    if not stripped.startswith(COMMAND_PREFIX):
        return None
    rest = stripped[len(COMMAND_PREFIX):]
    # "/qa" 바로 뒤에 공백이나 줄바꿈이 있거나 끝이어야 한다. "/qatest"는 버린다.
    if rest and not rest[0].isspace():
        return None

    rest = rest.strip()
    commit = None
    match = COMMIT_PATTERN.match(rest)
    if match:
        commit = match.group(1).lower()
        rest = rest[match.end():].strip()

    truncated = len(rest) > MAX_TEXT_CHARS
    return {"commit": commit, "text": rest[:MAX_TEXT_CHARS], "truncated": truncated}


def main():
    try:
        config = load_config()
    except ConfigError as exc:
        # 종료 코드 1이면 Hermes가 이 메시지를 로그에 남긴다.
        sys.stderr.write(str(exc))
        sys.exit(1)
    try:
        payload = json.load(sys.stdin)
    except (json.JSONDecodeError, OSError):
        return
    result = decide(payload, config)
    if result is not None:
        sys.stdout.write(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
