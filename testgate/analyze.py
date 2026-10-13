"""분석 전체 흐름. 입력 조각(diff 소스, 지식 소스, 실행기)은 바꿔 끼울 수 있다."""

from testgate import prompt, report, schema

MAX_PROMPT_CHARS = 400000


class AnalysisError(Exception):
    pass


def analyze(request, context, knowledge, runner):
    """요청과 PR 맥락을 분석해 결과 사전을 돌려준다.

    request: {"deliveryId", "repo", "pr", "commit", "text"}
    context: DiffSource가 만든 PR 맥락
    """
    docs = knowledge.load(context)
    user_prompt = prompt.build_user_prompt(request, context, docs)
    if len(user_prompt) > MAX_PROMPT_CHARS:
        raise AnalysisError(f"입력이 너무 커서 분석하지 않는다 ({len(user_prompt)}자)")

    raw, meta = runner.run(prompt.SYSTEM_PROMPT, user_prompt, schema.OUTPUT_SCHEMA)
    try:
        shaped = schema.validate_shape(raw)
    except schema.OutputError as exc:
        raise AnalysisError(f"Claude 출력이 스키마와 다르다: {exc}")

    result, notes = schema.postprocess(shaped, context["files"], request["text"])
    if context["truncated"]:
        notes.append("diff가 너무 커서 일부 파일은 내용을 보지 못했습니다.")
    verdict = schema.verdict(result)
    name = report.session_name(request["pr"], request.get("commit"))
    markdown = report.render(request, context, result, verdict, notes, name)
    return {
        "markdown": markdown,
        "verdict": verdict,
        "mode": result["mode"],
        "session_name": name,
        "notes": notes,
        "result": result,
        "meta": meta,
        "prompt_chars": len(user_prompt),
    }
