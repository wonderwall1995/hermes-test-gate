"""보고서를 하나의 HTML 파일로 만든다. 틀(CSS 포함)은 이 파일에 미리 구비되어 있고 본문만 끼워 넣는다.

스크립트와 외부 자원이 없다. 모델이 쓴 문장은 모두 이스케이프해서 넣는다.
GitHub 코멘트는 CSS를 지우므로 칸 너비와 왼쪽 번호 고정은 이 파일에서만 된다.
"""

import html

from testgate import budget, report

STYLE = """
:root { color-scheme: light dark; --line:#8884; --muted:#888; --accent:#2f6feb; }
body { font: 15px/1.6 system-ui, sans-serif; max-width: 1200px; margin: 0 auto; padding: 24px 16px 64px; }
h1 { font-size: 1.5rem; margin: 0 0 8px; } h2 { font-size: 1.15rem; margin: 28px 0 8px; }
.meta { color: var(--muted); margin: 0 0 16px; padding: 0; list-style: none; }
.hint { color: var(--muted); font-size: .9rem; }
details { border: 1px solid var(--line); border-radius: 8px; margin: 10px 0; }
summary { cursor: pointer; padding: 10px 14px; font-weight: 600; }
.grid { overflow-x: auto; padding: 0 14px 12px; }
table { border-collapse: collapse; width: 100%; table-layout: fixed; }
th, td { border-bottom: 1px solid var(--line); padding: 8px 10px; text-align: left; vertical-align: top; overflow-wrap: anywhere; }
th { font-size: .85rem; color: var(--muted); }
td.num, th.num { width: 2.2rem; padding-left: 4px; padding-right: 6px; position: sticky; left: 0; background: Canvas; text-align: right; color: var(--muted); }
td.path, th.path { width: 13%; font-size: .85rem; } td.step { width: 46%; } td.exp { width: 34%; }
td.sum { width: 25%; } td.state { width: 7rem; } td.quote { width: 30%; }
code { font: 13px ui-monospace, monospace; }
ul { padding-left: 1.2rem; }
"""


def _e(text):
    return html.escape(str(text), quote=True)


def _multi(parts):
    return "<br>".join(_e(p) for p in parts if str(p).strip())


def _design_rows(rows):
    out, number = [], 0
    for c in rows:
        if c.get("carried_from"):
            number += 1
            out.append(f'<tr><td class="num">{number}</td><td class="path"><code>{_e(c["path"])}</code></td>'
                       f'<td class="step">이전 요청 {_e(c["carried_from"])}에서 확인됨</td><td class="exp">-</td></tr>')
            continue
        for sc in c["scenarios"] or [None]:
            number += 1
            if sc is None:
                attempt, expected = f'{_e(c["change_summary"])} (제안된 시나리오 없음)', "-"
            else:
                attempt = _multi([sc["title"], *[f"{i}. {s}" for i, s in enumerate(sc["steps"], 1)]])
                expected = _e(sc["expected"])
            out.append(f'<tr><td class="num">{number}</td><td class="path"><code>{_e(c["path"])}</code></td>'
                       f'<td class="step">{attempt}</td><td class="exp">{expected}</td></tr>')
    return ("<thead><tr><th class=\"num\">#</th><th class=\"path\">파일</th><th>테스트 시도 방법</th><th>기대 동작</th></tr></thead>",
            out)


def _evaluate_rows(rows):
    out = []
    for number, c in enumerate(rows, 1):
        quote = f"“{_e(c['evidence_quote'])}”" if c["evidence_quote"] else ""
        if c.get("carried_from"):
            quote = f"이전 요청 {_e(c['carried_from'])}에서 확인됨 {quote}".strip()
        out.append(f'<tr><td class="num">{number}</td><td class="path"><code>{_e(c["path"])}</code></td>'
                   f'<td class="sum">{_e(c["change_summary"])}</td><td class="state">{_e(report.TESTED_LABELS[c["tested"]])}</td>'
                   f'<td class="quote">{quote}</td></tr>')
    return ("<thead><tr><th class=\"num\">#</th><th class=\"path\">파일</th><th>변경 요약</th><th>테스트</th><th>근거</th></tr></thead>",
            out)


def _list(title, items):
    if not items:
        return ""
    return f"<h2>{_e(title)}</h2><ul>" + "".join(f"<li>{i}</li>" for i in items) + "</ul>"


def render_html(request, context, result, verdict, notes, name):
    design = result["mode"] == "design"
    groups = report.by_category(result["changes"])
    target = f"PR #{request['pr']} (기준 브랜치 {context['base_ref']})"
    if request.get("commit"):
        target += f", 커밋 {request['commit']}"
    meta = [f"대상: {_e(target)}"]
    if not design:
        done = sum(1 for c in result["changes"] if c["tested"] == "yes")
        meta.append(f"판정: <b>{_e(report.VERDICT_LABELS[verdict])}</b> (테스트 확인된 변경 {done}/{len(result['changes'])})")
    cov = report._coverage_line(result["changes"])
    if cov:
        meta.append(_e(cov.lstrip("- ")))
    body = [f"<h1>{'테스트 설계서' if design else 'QA 테스트 평가 보고서'}</h1>",
            "<ul class=\"meta\">" + "".join(f"<li>{m}</li>" for m in meta) + "</ul>",
            f"<h2>요약</h2><p>{_e(result['summary']) or '(요약 없음)'}</p>",
            f"<h2>변경 카테고리별 {'테스트' if design else '확인'}</h2>"]
    if design:
        body.append('<p class="hint">가설 초안입니다. 중요도는 검증하지 않았습니다.</p>')
    claims = result.get("description_claims") or []
    if claims:
        trs = []
        for number, claim in enumerate(claims, 1):
            files = "".join(f"<br><code>{_e(f)}</code>" for f in claim["files"])
            trs.append(f'<tr><td class="num">{number}</td><td class="step">“{_e(claim["quote"])}”</td>'
                       f'<td class="sum">{_e(report.CLAIM_LABELS[claim["status"]])}{files}</td>'
                       f'<td class="step">{_e(claim["check"])}</td><td class="exp">{_e(claim["expected"])}</td></tr>')
        body.append('<h2>PR 설명 대조</h2><p class="hint">설명의 인용은 코드가 설명 원문과 대조했습니다. 설명은 작성자의 주장이며 사실로 확인된 것이 아닙니다.</p>'
                    f'<details open><summary>PR 설명 대조 ({len(claims)})</summary><div class="grid"><table><thead><tr>'
                    '<th class="num">#</th><th>설명의 주장 (원문 인용)</th><th>diff 대조</th><th>테스트 시도 방법</th><th>기대 동작</th>'
                    "</tr></thead><tbody>" + "".join(trs) + "</tbody></table></div></details>")
    for key, label in report.CATEGORIES:
        rows = groups[key]
        if not rows:
            continue
        head, trs = _design_rows(rows) if design else _evaluate_rows(rows)
        body.append(f'<details open><summary>{_e(label)} ({len(rows)})</summary><div class="grid"><table>{head}<tbody>'
                    + "".join(trs) + "</tbody></table></div></details>")
    if not design:
        pending = [c for c in result["changes"] if c["tested"] != "yes" and c.get("coverage") not in ("unseen", "excluded")]
        body.append(_list("추가로 이행해야 할 테스트", [f"<code>{_e(c['path'])}</code>: {_e(c['request'])}" for c in pending]))
    excluded = [c for c in result["changes"] if c.get("coverage") == "excluded"]
    body.append(_list("분석에서 제외한 파일", [f"<code>{_e(c['path'])}</code>" for c in excluded]))
    unseen = [c for c in result["changes"] if c.get("coverage") == "unseen"]
    body.append(_list("확인하지 못한 파일", [
        f"<code>{_e(c['path'])}</code>: {_e(budget.reason_label(c.get('reason', '')))}. {_e(c['request'])}" for c in unseen]))
    partial = [c for c in result["changes"] if c.get("coverage") == "partial"]
    body.append(_list("일부만 읽은 파일", [
        f"<code>{_e(c['path'])}</code>: {_e(budget.reason_label(c.get('reason', '')))}" for c in partial]))
    all_notes = ([result["notes"]] if result["notes"].strip() else []) + list(notes)
    body.append(_list("비고", [_e(n) for n in all_notes]))
    body.append(f'<hr><p class="hint">세션: <code>{_e(name)}</code></p>')
    return ("<!doctype html>\n<html lang=\"ko\"><head><meta charset=\"utf-8\">"
            "<meta http-equiv=\"Content-Security-Policy\" content=\"default-src 'none'; style-src 'unsafe-inline'\">"
            "<meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">"
            f"<title>{_e(name)}</title><style>{STYLE}</style></head><body>\n" + "\n".join(b for b in body if b)
            + "\n</body></html>\n")
