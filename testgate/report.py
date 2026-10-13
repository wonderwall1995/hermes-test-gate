"""분석 결과를 마크다운 보고서로 만든다. 모델이 쓴 문장은 모두 이스케이프한다."""

import re

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


def render(request, context, result, verdict, notes, name):
    target = f"PR #{request['pr']} (기준 브랜치 {code(context['base_ref'])})"
    if request.get("commit"):
        target += f", 커밋 {code(request['commit'])}"
    lines = []
    if result["mode"] == "design":
        lines.append("# 테스트 설계서")
    else:
        lines.append("# QA 테스트 평가 보고서")
    lines += ["", f"- 대상: {target}"]
    if result["mode"] == "evaluate":
        total = len(result["changes"])
        done = sum(1 for c in result["changes"] if c["tested"] == "yes")
        lines.append(f"- 판정: **{VERDICT_LABELS[verdict]}** (테스트 확인된 변경 {done}/{total})")
    lines += ["", "## 요약", "", esc(result["summary"]) or "(요약 없음)", ""]

    if result["mode"] == "evaluate":
        lines += ["## 변경별 확인", "", "| 파일 | 변경 요약 | 테스트 | 근거 |", "| --- | --- | --- | --- |"]
        for c in result["changes"]:
            quote = f"“{cell(c['evidence_quote'])}”" if c["evidence_quote"] else ""
            if c.get("carried_from"):
                # 이전 요청에서 확인되어 이어받은 항목. 어느 세션에서 확인되었는지 보여 준다.
                quote = f"이전 요청 {code(c['carried_from'])}에서 확인됨 {quote}".strip()
            lines.append(f"| {code(c['path'])} | {cell(c['change_summary'])} | {TESTED_LABELS[c['tested']]} | {quote} |")
        pending = [c for c in result["changes"] if c["tested"] != "yes"]
        if pending:
            lines += ["", "## 추가로 이행해야 할 테스트", ""]
            for number, c in enumerate(pending, 1):
                lines.append(f"{number}. {code(c['path'])}: {esc(c['request'])}")
    else:
        lines += ["## 변경별 시나리오", ""]
        for c in result["changes"]:
            lines.append(f"### {code(c['path'])}")
            if c.get("carried_from"):
                lines += ["", f"이전 요청 {code(c['carried_from'])}에서 확인되어 새 시나리오를 만들지 않았습니다.", ""]
                continue
            if c["change_summary"]:
                lines += ["", esc(c["change_summary"])]
            if not c["scenarios"]:
                lines += ["", "(제안된 시나리오 없음)"]
            for number, sc in enumerate(c["scenarios"], 1):
                lines += ["", f"**{number}. {esc(sc['title'])}**", ""]
                for step_number, step in enumerate(sc["steps"], 1):
                    lines.append(f"{step_number}. {esc(step)}")
                lines += ["", f"기대 결과: {esc(sc['expected'])}"]
            lines.append("")

    all_notes = ([result["notes"]] if result["notes"].strip() else []) + list(notes)
    if all_notes:
        lines += ["", "## 비고", ""]
        lines += [f"- {esc(n)}" for n in all_notes]
    lines += ["", "---", f"세션: {code(name)}", ""]
    return "\n".join(lines)


def render_free(answer, name):
    """자유 대화 답변. 판정 표 없이 답변과 맨 아래 세션 이름만 쓴다."""
    body = esc_markdown(answer).strip() or "(답변 없음)"
    return f"{body}\n\n---\n세션: {code(name)}\n"
