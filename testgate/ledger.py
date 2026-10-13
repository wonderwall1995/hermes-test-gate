"""PR 단위 대화 기록. 같은 PR의 이전 요청을 기억해서 요청 순번을 매기고, 확인된 파일을 이어받게 한다.

위치: $HERMES_HOME/testgate/threads/<소유자>__<레포>__<PR번호>.json (권한 600)
소유자는 개인과 조직 모두 같은 형식의 로그인 이름이다.
Hermes 세션은 요청마다 따로 생기므로, PR 단위의 연속성은 이 파일이 맡는다.
이 파일은 testgate만 쓴다. 판정은 코드가 하며 Claude의 기억에 의존하지 않는다.
"""

import contextlib
import fcntl
import hashlib
import json
import os
import pathlib
import time

from testgate import diffsource

MAX_ENTRIES = 50
HISTORY_CHARS = 6000


def thread_path(home, repo, pr):
    owner, name = repo.split("/", 1)
    return pathlib.Path(home) / "testgate" / "threads" / f"{owner}__{name}__{int(pr)}.json"


@contextlib.contextmanager
def locked(path):
    """같은 PR에 요청이 동시에 와도 순번이 겹치지 않게 파일 잠금을 건다."""
    path.parent.mkdir(parents=True, exist_ok=True)
    handle = open(str(path) + ".lock", "a")
    try:
        fcntl.flock(handle, fcntl.LOCK_EX)
        yield
    finally:
        fcntl.flock(handle, fcntl.LOCK_UN)
        handle.close()


def load(path, repo, pr):
    """기록을 읽는다. 없거나 깨졌으면 빈 기록을 돌려준다. 깨진 파일은 .bad로 옮겨 둔다."""
    empty = {"repo": repo, "pr": int(pr), "next_seq": 1, "titles": [], "entries": []}
    try:
        data = json.loads(pathlib.Path(path).read_text(encoding="utf-8"))
    except FileNotFoundError:
        return empty
    except (OSError, json.JSONDecodeError):
        try:
            os.replace(path, str(path) + ".bad")
        except OSError:
            pass
        return empty
    if not isinstance(data, dict) or not isinstance(data.get("entries"), list):
        return empty
    data.setdefault("next_seq", 1 + max([e.get("seq", 0) for e in data["entries"]] or [0]))
    data.setdefault("titles", [])
    return data


def save(path, data):
    path = pathlib.Path(path)
    temp = path.with_name(f".{path.name}.tmp")
    fd = os.open(temp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as handle:
        json.dump(data, handle, ensure_ascii=False, indent=1)
    os.replace(temp, path)


def reserve(home, repo, pr, delivery_id, now=time.time):
    """이 요청의 순번을 정한다. 같은 delivery ID로 다시 부르면 같은 순번을 돌려준다."""
    path = thread_path(home, repo, pr)
    with locked(path):
        data = load(path, repo, pr)
        for entry in data["entries"]:
            if entry.get("deliveryId") == delivery_id:
                return entry["seq"]
        seq = data["next_seq"]
        data["next_seq"] = seq + 1
        data["entries"].append({"seq": seq, "deliveryId": delivery_id, "at": int(now()), "status": "pending"})
        data["entries"] = data["entries"][-MAX_ENTRIES:]
        save(path, data)
        return seq


def finalize(home, repo, pr, delivery_id, record, title=None, now=time.time):
    """요청 결과를 기록한다. record는 status, kind, session 등 요청별 값이다."""
    path = thread_path(home, repo, pr)
    with locked(path):
        data = load(path, repo, pr)
        entry = next((e for e in data["entries"] if e.get("deliveryId") == delivery_id), None)
        if entry is None:
            seq = record.get("seq") or data["next_seq"]
            data["next_seq"] = max(data["next_seq"], seq + 1)
            entry = {"seq": seq, "deliveryId": delivery_id, "at": int(now())}
            data["entries"].append(entry)
            data["entries"] = data["entries"][-MAX_ENTRIES:]
        entry.update(record)
        if title and (not data["titles"] or data["titles"][-1].get("title") != title):
            data["titles"].append({"at": int(now()), "title": title})
            data["titles"] = data["titles"][-20:]
        save(path, data)


def done_entries(home, repo, pr):
    """끝난 요청 기록을 순번 순서로 돌려준다. 읽기만 하며 잠그지 않는다."""
    data = load(thread_path(home, repo, pr), repo, pr)
    return sorted((e for e in data["entries"] if e.get("status") == "done"), key=lambda e: e.get("seq", 0))


# ---- 이어받기

def fingerprint(scope, commit, block):
    """파일 하나의 diff 지문. 범위(PR 전체 또는 커밋 하나)가 다르면 지문도 다르다."""
    return hashlib.sha256(f"{scope}\0{commit or ''}\0{block}".encode("utf-8")).hexdigest()


def file_fingerprints(context):
    """{경로: 지문}. diff 내용을 보지 못한 파일은 지문이 없고 이어받지 않는다."""
    blocks = diffsource.blocks_by_path(context["diff"])
    result = {}
    for f in context["files"]:
        block = blocks.get(f["path"])
        if block is not None and f.get("diff_included", True):
            result[f["path"]] = fingerprint(context["scope"], context.get("commit"), block)
    return result


def carry_over(entries, files, fingerprints):
    """이전 요청에서 확인됨(yes)이고 지문이 그대로인 파일을 찾는다.

    같은 지문이 있는 가장 최근 기록이 판단한다. 반환: (이어받은 파일 {경로: 기록}, 변경되어 다시 확인할 파일 목록)
    """
    carried, stale = {}, []
    for f in files:
        path = f["path"]
        fp = fingerprints.get(path)
        was_verified = False
        decided = None
        for entry in reversed(entries):
            record = (entry.get("files") or {}).get(path)
            if not record:
                continue
            if record.get("tested") == "yes":
                was_verified = True
            if fp and record.get("fp") == fp:
                decided = record
                break
        if decided and decided.get("tested") == "yes":
            carried[path] = decided
        elif decided is None and was_verified:
            # 예전에는 확인됐지만 지금 지문과 맞는 기록이 없다. 그 뒤 파일이 바뀌었다는 뜻이다.
            stale.append(path)
    return carried, stale


# ---- Claude에 줄 이전 기록 요약

def render_history(entries, limit=5, max_chars=HISTORY_CHARS):
    """최근 요청 몇 건의 요약. Claude에는 비신뢰 데이터로 전달한다."""
    lines = []
    for entry in entries[-limit:]:
        head = f"#{entry.get('seq')} {entry.get('kind', '?')} {entry.get('session', '')}".strip()
        if entry.get("commit"):
            head += f" commit={entry['commit']}"
        lines.append(head)
        if entry.get("kind") == "free":
            lines.append(f"  question: {entry.get('question', '')}")
            lines.append(f"  answer: {entry.get('answer', '')}")
            continue
        if entry.get("summary"):
            lines.append(f"  summary: {entry['summary']}")
        for path, record in (entry.get("files") or {}).items():
            line = f"  {path}: {record.get('tested')}"
            if record.get("request"):
                line += f" | requested: {record['request']}"
            lines.append(line)
    text = "\n".join(lines)
    return text[-max_chars:] if len(text) > max_chars else text
