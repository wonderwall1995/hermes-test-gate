"""분석 결과를 마크다운 보고서로 만든다. 모델이 쓴 문장은 모두 이스케이프한다."""

TESTED_LABELS = {"yes": "확인됨", "partial": "일부", "no": "언급 없음", "unclear": "확인 불가"}
VERDICT_LABELS = {
    "sufficient": "충족",
    "more_tests_needed": "추가 테스트 필요",
    "design": "설계서",
}


def session_name(pr_number, commit=None):
    """세션 이름. 커밋ID는 코멘트에 있을 때만 붙인다."""
    return f"[PR{pr_number}-{commit}]" if commit else f"[PR{pr_number}]"


def esc(text):
    """모델이 쓴 문장이 멘션, HTML, 표 구조를 깨지 않게 한다."""
    text = str(text).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    return text.replace("@", "@\u200b")


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
