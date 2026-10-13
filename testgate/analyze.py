"""분석 전체 흐름. 입력 조각(diff 소스, 지식 소스, 실행기)은 바꿔 끼울 수 있다."""

from testgate import diffsource, ledger, prompt, report, schema

MAX_PROMPT_CHARS = 400000
ALL_VERIFIED_SUMMARY = "이 PR의 변경 파일은 모두 이전 요청에서 이미 확인되어 새로 평가하지 않았습니다."


class AnalysisError(Exception):
    pass


def reduced_context(context, keep_paths):
    """평가할 파일만 남긴 맥락. 이미 확인된 파일의 diff는 빼서 입력을 줄인다."""
    keep = set(keep_paths)
    blocks = diffsource.blocks_by_path(context["diff"])
    files = [f for f in context["files"] if f["path"] in keep]
    diff = "".join(blocks[f["path"]] for f in files if f["path"] in blocks and f.get("diff_included", True))
    return dict(context, files=files, diff=diff)


def _check_size(user_prompt):
    if len(user_prompt) > MAX_PROMPT_CHARS:
        raise AnalysisError(f"입력이 너무 커서 분석하지 않는다 ({len(user_prompt)}자)")


def _default_name(request, context):
    return report.session_name(request["pr"], context.get("title"), request.get("commit"), None)


def analyze(request, context, knowledge, runner, history=None, name=None):
    """요청과 PR 맥락을 평가하거나 설계서를 만든다.

    request: {"deliveryId", "repo", "pr", "commit", "text"}
    context: DiffSource가 만든 PR 맥락
    history: 이 PR의 이전 요청 기록(ledger.done_entries). 확인됨을 이어받는 데 쓴다.
    name:    세션 이름. 없으면 PR 번호와 이름으로 만든다.
    """
    history = history or []
    name = name or _default_name(request, context)
    fingerprints = ledger.file_fingerprints(context)
    carried, stale = ledger.carry_over(history, context["files"], fingerprints)
    to_evaluate = [f for f in context["files"] if f["path"] not in carried]
    notes = []
    if stale:
        notes.append("이전 요청에서 확인됐지만 그 뒤 변경되어 다시 확인이 필요한 파일: " + ", ".join(stale))

    prompt_chars = 0
    if to_evaluate:
        docs = knowledge.load(context)
        user_prompt = prompt.build_user_prompt(
            request, reduced_context(context, [f["path"] for f in to_evaluate]), docs,
            history=ledger.render_history(history), verified=sorted(carried),
        )
        _check_size(user_prompt)
        prompt_chars = len(user_prompt)
        raw, meta = runner.run(prompt.SYSTEM_PROMPT, user_prompt, schema.OUTPUT_SCHEMA)
        try:
            shaped = schema.validate_shape(raw)
        except schema.OutputError as exc:
            raise AnalysisError(f"Claude 출력이 스키마와 다르다: {exc}")
        result, post_notes = schema.postprocess(shaped, to_evaluate, request["text"])
        notes += post_notes
    else:
        # 평가할 파일이 없으면 Claude를 부르지 않는다.
        result = {"mode": "evaluate", "summary": ALL_VERIFIED_SUMMARY, "changes": [], "notes": ""}
        meta = {"cost_usd": 0, "duration_ms": 0, "models": []}

    judged = {c["path"]: c for c in result["changes"]}
    merged = []
    for f in context["files"]:
        record = carried.get(f["path"])
        if record is not None:
            merged.append({
                "path": f["path"], "change_summary": record.get("summary", ""), "tested": "yes",
                "evidence_quote": record.get("evidence", ""), "request": "", "scenarios": [],
                "carried_from": record.get("session", ""),
            })
        else:
            merged.append(judged[f["path"]])
    result = dict(result, changes=merged)

    if context["truncated"]:
        notes.append("diff가 너무 커서 일부 파일은 내용을 보지 못했습니다.")
    verdict = schema.verdict(result)
    markdown = report.render(request, context, result, verdict, notes, name)

    files_record = {}
    for c in merged:
        carried_record = carried.get(c["path"])
        files_record[c["path"]] = {
            "tested": c["tested"], "fp": fingerprints.get(c["path"]), "evidence": c["evidence_quote"],
            "summary": c["change_summary"], "request": c["request"],
            "session": carried_record.get("session") if carried_record else name,
        }
    return {
        "markdown": markdown, "verdict": verdict, "mode": result["mode"], "session_name": name,
        "notes": notes, "result": result, "meta": meta, "prompt_chars": prompt_chars,
        "files_record": files_record, "summary": result["summary"],
    }


def analyze_free(request, context, knowledge, runner, history=None, name=None):
    """자유 대화. 보고서 없이 답변만 만든다. diff 본문은 커밋ID가 주어졌을 때만 준다."""
    history = history or []
    name = name or _default_name(request, context)
    if not request.get("commit"):
        context = dict(context, diff="")
    user_prompt = prompt.build_free_prompt(request, context, knowledge.load(context), ledger.render_history(history))
    _check_size(user_prompt)
    raw, meta = runner.run(prompt.FREE_SYSTEM_PROMPT, user_prompt, schema.FREE_SCHEMA)
    try:
        answer = schema.validate_free(raw)
    except schema.OutputError as exc:
        raise AnalysisError(f"Claude 출력이 스키마와 다르다: {exc}")
    return {
        "markdown": report.render_free(answer, name), "verdict": "-", "mode": "free", "session_name": name,
        "notes": [], "result": {"answer": answer}, "meta": meta, "prompt_chars": len(user_prompt),
        "files_record": {}, "summary": "", "answer": answer,
    }
