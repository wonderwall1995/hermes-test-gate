"""분석 결과를 마크다운 보고서로 만든다. 모델이 쓴 문장은 모두 이스케이프한다."""

import re

from testgate import budget

TESTED_LABELS = {"yes": "확인됨", "partial": "일부", "no": "언급 없음", "unclear": "확인 불가"}
VERDICT_LABELS = {
    "sufficient": "충족",
    "more_tests_needed": "추가 테스트 필요",
    "design": "설계서",
}


TITLE_LIMIT = 40
ZERO_WIDTH = "\u200b"


def clean_title(title, limit=TITLE_LIMIT):
    """PR 이름을 세션 이름에 넣을 수 있게 정리한다. 대괄호, 백틱, 줄바꿈을 없애고 길이를 제한한다."""
    text = re.sub(r"[\[\]`\r\n\t]+", " ", str(title or ""))
    text = "".join(ch for ch in text if ch.isprintable())
    text = " ".join(text.split())
    if len(text) > limit:
        text = text[:limit].rstrip() + "…"
    return text


def session_name(pr_number, title=None, commit=None, seq=None):
    """세션 이름: [PR번호 - PR이름 - 커밋ID #순번]. PR이름, 커밋ID, 순번은 있을 때만 붙인다."""
    parts = [f"PR{pr_number}"]
    cleaned = clean_title(title)
    if cleaned:
        parts.append(cleaned)
    if commit:
        parts.append(str(commit))
    name = " - ".join(parts)
    if seq:
        name += f" #{seq}"
    return f"[{name}]"


def defang(text):
    """마크다운 이미지와 링크 문법을 깨뜨린다. 이미지는 GitHub이 대신 불러오므로 PR 내용이 주소에 실려 나갈 수 있다."""
    return text.replace("![", "!" + ZERO_WIDTH + "[").replace("](", "]" + ZERO_WIDTH + "(")


def esc(text):
    """모델이 쓴 문장이 멘션, HTML, 이미지, 표 구조를 깨지 않게 한다."""
    text = str(text).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    return defang(text.replace("@", "@" + ZERO_WIDTH))


def esc_markdown(text):
    """자유 서술 답변용. 코드 블록 안은 그대로 두고 바깥만 이스케이프한다. 멘션과 이미지는 어디서나 막는다."""
    out = []
    in_fence = False
    for line in str(text).splitlines():
        if line.lstrip().startswith("```"):
            in_fence = not in_fence
            out.append(line)
            continue
        if in_fence:
            out.append(defang(line.replace("@", "@" + ZERO_WIDTH)))
        else:
            out.append(esc(line))
    if in_fence:
        out.append("```")
    return "\n".join(out)


def cell(text):
    return esc(text).replace("|", "\\|").replace("\r", " ").replace("\n", " ")


def code(text):
    """경로처럼 백틱으로 감싸는 값. 백틱과 줄바꿈은 제거한다."""
    return "`" + str(text).replace("`", "'").replace("\n", " ") + "`"


def _coverage_line(changes):
    counts = {"full": 0, "partial": 0, "unseen": 0, "excluded": 0}
    for c in changes:
        if c.get("coverage") in counts and not c.get("carried_from"):
            counts[c["coverage"]] += 1
    if not (counts["partial"] or counts["unseen"] or counts["excluded"]):
        return ""
    return (f"- 판독 범위: 전체 {counts['full']}, 일부 {counts['partial']}, "
            f"제외 {counts['excluded']}, 미확인 {counts['unseen']}")


# 변경 카테고리. 순서가 곧 보고서의 순서이다. 분류는 파일 상태와 경로로 코드가 정하며 모델은 관여하지 않는다.
CATEGORIES = (
    ("modified", "수정된 코드"),
    ("added", "추가된 코드"),
    ("removed", "삭제된 코드"),
    ("docs", "SQL·문서·기타"),
)
DOC_EXTENSIONS = (".sql", ".md", ".mdx", ".rst", ".txt")


def categorize(change):
    """변경 한 건의 카테고리 키. SQL과 문서는 상태와 무관하게 따로 모은다."""
    path = str(change["path"]).lower()
    if path.endswith(DOC_EXTENSIONS) or path.split("/")[0] == "docs":
        return "docs"
    status = change.get("status", "modified")
    if status == "removed":
        return "removed"
    if status == "added":
        return "added"
    return "modified"


def by_category(changes):
    """읽은 변경을 카테고리별로 묶는다. 제외와 미확인 파일은 따로 다루므로 여기에 넣지 않는다."""
    groups = {key: [] for key, _ in CATEGORIES}
    for c in changes:
        if c.get("coverage") in ("unseen", "excluded"):
            continue
        groups[categorize(c)].append(c)
    return groups


def path_code(path):
    """표 안의 경로. 슬래시 뒤에 폭 없는 줄바꿈 자리를 둬서 긴 경로가 열 폭을 늘리지 않고 접히게 한다 (GitHub 표는 열 폭을 지정할 수 없다)."""
    return code(path).replace("/", "/\u200b")


def cell_join(parts):
    """셀 안의 줄바꿈. 조각마다 이스케이프한 뒤 <br>로 잇는다."""
    return "<br>".join(cell(p) for p in parts if str(p).strip())


def _accordion(title, count, body_lines):
    return [f"<details><summary><b>{title} ({count})</b></summary>", "", *body_lines, "", "</details>", ""]


def _design_grid(rows):
    lines = ["| # | 파일 | 테스트 시도 방법 | 기대 동작 |", "| --- | --- | --- | --- |"]
    number = 0
    for c in rows:
        if c.get("carried_from"):
            number += 1
            lines.append(f"| {number} | {path_code(c['path'])} | 이전 요청 {code(c['carried_from'])}에서 확인됨 | - |")
            continue
        scenarios = c["scenarios"] or [None]
        for sc in scenarios:
            number += 1
            if sc is None:
                lines.append(f"| {number} | {path_code(c['path'])} | {cell(c['change_summary'])} (제안된 시나리오 없음) | - |")
                continue
            steps = [f"{i}. {step}" for i, step in enumerate(sc["steps"], 1)]
            lines.append(f"| {number} | {path_code(c['path'])} | {cell_join([sc['title'], *steps])} | {cell(sc['expected'])} |")
    return lines


def _evaluate_grid(rows):
    lines = ["| # | 파일 | 변경 요약 | 테스트 | 근거 |", "| --- | --- | --- | --- | --- |"]
    for number, c in enumerate(rows, 1):
        quote = f"“{cell(c['evidence_quote'])}”" if c["evidence_quote"] else ""
        if c.get("carried_from"):
            # 이전 요청에서 확인되어 이어받은 항목. 어느 세션에서 확인되었는지 보여 준다.
            quote = f"이전 요청 {code(c['carried_from'])}에서 확인됨 {quote}".strip()
        lines.append(f"| {number} | {path_code(c['path'])} | {cell(c['change_summary'])} | {TESTED_LABELS[c['tested']]} | {quote} |")
    return lines


CLAIM_LABELS = {
    "in_diff": "diff에서 확인됨",
    "not_in_diff": "설명에는 있으나 diff에서 확인되지 않음",
    "unclear": "판단 불가",
}


def _claims_grid(claims):
    lines = ["| # | 설명의 주장 (원문 인용) | diff 대조 | 테스트 시도 방법 | 기대 동작 |", "| --- | --- | --- | --- | --- |"]
    for number, claim in enumerate(claims, 1):
        state = cell_join([CLAIM_LABELS[claim["status"]], *[f"`{f}`" for f in claim["files"]]]) if claim["files"] else cell(CLAIM_LABELS[claim["status"]])
        lines.append(f"| {number} | “{cell(claim['quote'])}” | {state} | {cell(claim['check'])} | {cell(claim['expected'])} |")
    return lines


def _tail_sections(result, notes, name):
    """제외, 미확인, 일부 읽음 목록과 비고. 모드와 상관없이 같다."""
    lines = []
    excluded = [c for c in result["changes"] if c.get("coverage") == "excluded"]
    if excluded:
        lines += ["", "## 분석에서 제외한 파일", "", "제외 규칙에 해당해 읽지도 판정하지도 않았습니다. 규칙은 testgate.json 에서 바꿉니다.", ""]
        lines += [f"- {code(c['path'])}" for c in excluded]
    unseen = [c for c in result["changes"] if c.get("coverage") == "unseen"]
    if unseen:
        lines += ["", "## 확인하지 못한 파일", "", "아래 파일은 diff를 읽지 못해 판단하지 않았습니다.", ""]
        for c in unseen:
            lines.append(f"- {code(c['path'])}: {esc(budget.reason_label(c.get('reason', '')))}. {esc(c['request'])}".rstrip())
    partial = [c for c in result["changes"] if c.get("coverage") == "partial"]
    if partial:
        lines += ["", "## 일부만 읽은 파일", ""]
        for c in partial:
            lines.append(f"- {code(c['path'])}: {esc(budget.reason_label(c.get('reason', '')))}")
    all_notes = ([result["notes"]] if result["notes"].strip() else []) + list(notes)
    if all_notes:
        lines += ["", "## 비고", ""]
        lines += [f"- {esc(n)}" for n in all_notes]
    lines += ["", "---", f"세션: {code(name)}", ""]
    return lines


def _header(request, context, result, verdict):
    target = f"PR #{request['pr']} (기준 브랜치 {code(context['base_ref'])})"
    if request.get("commit"):
        target += f", 커밋 {code(request['commit'])}"
    lines = ["# 테스트 설계서" if result["mode"] == "design" else "# QA 테스트 평가 보고서", "", f"- 대상: {target}"]
    if result["mode"] == "evaluate":
        total = len(result["changes"])
        done = sum(1 for c in result["changes"] if c["tested"] == "yes")
        lines.append(f"- 판정: **{VERDICT_LABELS[verdict]}** (테스트 확인된 변경 {done}/{total})")
    cov = _coverage_line(result["changes"])
    if cov:
        lines.append(cov)
    lines += ["", "## 요약", "", esc(result["summary"]) or "(요약 없음)", ""]
    return lines


def render(request, context, result, verdict, notes, name, compact=False):
    """코멘트로 올리는 보고서. 카테고리마다 접는 영역이 있고 그 안에 번호 붙은 표가 들어간다.

    compact=True 이면 표를 빼고 카테고리별 개수만 쓴다. 코멘트 길이 한도를 넘을 때 쓴다.
    """
    lines = _header(request, context, result, verdict)
    groups = by_category(result["changes"])
    design = result["mode"] == "design"
    claims = result.get("description_claims") or []
    if claims:
        lines += ["## PR 설명 대조", "", "설명의 인용은 코드가 설명 원문과 대조했습니다. 설명은 작성자의 주장이며 사실로 확인된 것이 아닙니다.", ""]
        if compact:
            lines += [f"- 설명의 주장 {len(claims)}개 (표는 길이 한도로 생략)", ""]
        else:
            lines += _accordion("PR 설명 대조", len(claims), _claims_grid(claims))
    lines += ["## 변경 카테고리별 테스트" if design else "## 변경 카테고리별 확인", ""]
    if design:
        lines += ["가설 초안입니다. 중요도는 검증하지 않았습니다.", ""]
    if compact:
        lines += ["코멘트 길이 한도를 넘어 표를 생략했습니다. 전체 내용은 서버의 보고서 파일(HTML)에 있습니다.", ""]
        lines += [f"- {label}: {len(groups[key])}개" for key, label in CATEGORIES if groups[key]]
    else:
        for key, label in CATEGORIES:
            rows = groups[key]
            if rows:
                grid = _design_grid(rows) if design else _evaluate_grid(rows)
                lines += _accordion(label, len(rows), grid)
    if not design:
        pending = [c for c in result["changes"] if c["tested"] != "yes" and c.get("coverage") not in ("unseen", "excluded")]
        if pending:
            lines += ["", "## 추가로 이행해야 할 테스트", ""]
            for number, c in enumerate(pending, 1):
                lines.append(f"{number}. {code(c['path'])}: {esc(c['request'])}")
    lines += _tail_sections(result, notes, name)
    return "\n".join(lines)


def render_free(answer, name):
    """자유 대화 답변. 판정 표 없이 답변과 맨 아래 세션 이름만 쓴다."""
    body = esc_markdown(answer).strip() or "(답변 없음)"
    return f"{body}\n\n---\n세션: {code(name)}\n"
