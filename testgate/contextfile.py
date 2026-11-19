"""분석 직전에 읽는 해설 파일(<배달ID>.context.json).

요청 파일(requests/<배달ID>.json) 옆에 다른 프로그램이 둔 참고 문서를 분석에 붙인다.
이 파일을 누가 만들었는지 모른다. 약속은 아래와 같다.

  {"version": 1, "docs": [{"id": "...", "title": "...", "text": "..."}], "notices": ["..."]}

- 파일이 없으면 아무 일도 하지 않는다. 이 기능이 없을 때와 똑같이 동작한다.
- 파일이 깨졌거나 읽을 수 없으면 해설 없이 분석을 이어가고, 사유 코드를 보고서 비고에 남긴다.
- 문서는 신뢰하지 않는 데이터이다. 길이와 개수를 제한하고, 프롬프트에는 데이터 블록으로만 들어간다.
- 보고서에는 제목과 안내만 나온다. 보고서의 이스케이프(멘션, HTML, 이미지·링크 문법)를 거치고, 맨 URL은 자동 링크가 되지 않게 깨뜨린다.
- 사유 코드만 보고서에 쓴다. 파일 안의 오류 문장이나 경로는 쓰지 않는다.
"""

import json
import logging
import os
import re
import stat

from testgate import knowledge

log = logging.getLogger("testgate")

VERSION = 1
MAX_FILE_BYTES = 2 * 1024 * 1024
MAX_DOCS = 50
MAX_NOTICES = 5
MAX_NOTICE_CHARS = 300
TITLE_LIMIT = 80
SHOWN_TITLES = 5

# 실패 사유 코드
UNREADABLE = "unreadable"
TOO_LARGE = "too_large"
BAD_OUTPUT = "bad_output"
UNSUPPORTED_VERSION = "unsupported_version"


class ContextFileError(Exception):
    def __init__(self, reason):
        self.reason = reason
        super().__init__(reason)


def plain(value, limit):
    """파일이 준 짧은 글을 보고서의 한 줄에 넣을 수 있게 한다: 공백을 하나로 모으고, 길이를 제한하고, 맨 URL을 깨뜨린다."""
    cleaned = re.sub(r"(?i)([a-z][a-z0-9+.-]*)://", r"\1 ", str(value))  # \b는 한글 바로 뒤의 주소를 놓친다
    cleaned = re.sub(r"(?i)www\.", "www ", cleaned)
    return " ".join(cleaned.split())[:limit]


def read_file(path):
    """파일을 읽어 (문서 목록, 안내 목록)을 돌려준다. 파일이 없으면 None. 문제가 있으면 ContextFileError."""
    try:
        # 심볼릭 링크는 따라가지 않는다. O_NONBLOCK은 FIFO를 열 때 멈추지 않게 한다.
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    except FileNotFoundError:
        return None
    except OSError:
        raise ContextFileError(UNREADABLE) from None
    try:
        if not stat.S_ISREG(os.fstat(fd).st_mode):
            raise ContextFileError(UNREADABLE)
        with os.fdopen(fd, "rb", closefd=False) as handle:
            data = handle.read(MAX_FILE_BYTES + 1)
    except OSError:
        raise ContextFileError(UNREADABLE) from None
    finally:
        os.close(fd)
    if len(data) > MAX_FILE_BYTES:
        raise ContextFileError(TOO_LARGE)
    return _validated(data)


def _validated(data):
    try:
        doc = json.loads(data.decode("utf-8"))
    except ValueError:
        raise ContextFileError(BAD_OUTPUT) from None
    version = doc.get("version") if isinstance(doc, dict) else None
    if not isinstance(version, int) or isinstance(version, bool):
        raise ContextFileError(BAD_OUTPUT)
    if version != VERSION:
        raise ContextFileError(UNSUPPORTED_VERSION)
    raw_docs = doc.get("docs", [])
    raw_notices = doc.get("notices", [])
    if not isinstance(raw_docs, list) or not isinstance(raw_notices, list) or not all(isinstance(n, str) for n in raw_notices):
        raise ContextFileError(BAD_OUTPUT)
    docs = []
    for item in raw_docs[:MAX_DOCS]:
        if not isinstance(item, dict) or not all(isinstance(item.get(k), str) for k in ("id", "title", "text")):
            raise ContextFileError(BAD_OUTPUT)
        if item["id"].strip() and item["text"].strip():
            docs.append({"id": item["id"], "title": item["title"], "text": item["text"]})
    notices = [plain(n, MAX_NOTICE_CHARS) for n in raw_notices[:MAX_NOTICES] if n.strip()]
    return docs, notices


class ContextFileKnowledge:
    """해설 파일 하나를 참고 문서 소스로 쓴다. 보고서에 남길 안내는 drain_notes로 꺼낸다."""

    def __init__(self, path, max_doc_chars=knowledge.MAX_DOC_CHARS, max_total_chars=knowledge.MAX_TOTAL_CHARS):
        self.path = path
        self.max_doc_chars = max_doc_chars
        self.max_total_chars = max_total_chars
        self._notes = []

    def load(self, context):
        try:
            got = read_file(self.path)
        except ContextFileError as exc:
            log.warning("해설 파일을 읽지 못함: %s", exc.reason)
            self._notes.append(f"참고 문서 파일을 읽지 못해 해설 없이 분석함 ({exc.reason}).")
            return []
        if got is None:
            return []
        raw_docs, notices = got
        docs, total, omitted = [], 0, 0
        for item in raw_docs:
            text = item["text"][: self.max_doc_chars]
            if total + len(text) > self.max_total_chars:
                omitted += 1
                continue
            total += len(text)
            docs.append({"id": item["id"], "title": item["title"], "text": text})
        if docs:
            titles = [plain(d["title"], TITLE_LIMIT) or d["id"] for d in docs[:SHOWN_TITLES]]
            more = f" 외 {len(docs) - SHOWN_TITLES}건" if len(docs) > SHOWN_TITLES else ""
            self._notes.append(f"참고 문서 {len(docs)}건이 첨부됨: {', '.join(titles)}{more}")
        if omitted:
            self._notes.append(f"참고 문서 {omitted}건은 크기 한도로 뺐습니다.")
        self._notes.extend(notices)
        return docs

    def drain_notes(self):
        notes, self._notes = self._notes, []
        return notes
