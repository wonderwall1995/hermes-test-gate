"""/qa 코멘트 문법. 코멘트 원문을 읽어 커밋ID, 자유 대화 여부, 서술로 나눈다.

controller는 접두어(/qa)만 보고 원문을 그대로 넘긴다. 문법은 이 모듈만 안다.

  /qa [커밋ID] 자유 서술        테스트 평가 또는 설계서
  /qa 자유 서술                 테스트 평가 또는 설계서
  /qa free: [커밋ID] 자유 서술  보고서 없는 자유 대화 (콜론이 붙은 소문자 free: 만 인정한다)
커밋ID는 대괄호 안의 16진수 7~40자이다. 대괄호가 없으면 전부 자유 서술로 본다.
코멘트 원문은 비신뢰 입력이다. 명령으로 실행하지 않는다.
"""

import re

COMMAND_PREFIX = "/qa"
FREE_PREFIX = "free:"
MAX_TEXT_CHARS = 10000
COMMIT_PATTERN = re.compile(r"^\[([0-9a-fA-F]{7,40})\]")


def parse_qa(body):
    """명령이 아니면 None. 맞으면 {"commit", "text", "truncated", "free"}."""
    stripped = body.strip()
    if not stripped.startswith(COMMAND_PREFIX):
        return None
    rest = stripped[len(COMMAND_PREFIX):]
    if rest and not rest[0].isspace():
        return None  # "/qatest"는 명령이 아니다
    rest = rest.strip()
    free = rest.startswith(FREE_PREFIX)
    if free:
        rest = rest[len(FREE_PREFIX):].strip()
    commit = None
    match = COMMIT_PATTERN.match(rest)
    if match:
        commit = match.group(1).lower()
        rest = rest[match.end():].strip()
    return {"commit": commit, "text": rest[:MAX_TEXT_CHARS], "truncated": len(rest) > MAX_TEXT_CHARS, "free": free}
