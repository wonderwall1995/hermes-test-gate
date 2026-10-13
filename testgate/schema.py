"""Claude 출력의 스키마, 검증, 후처리. 모델 출력은 신뢰하지 않고 코드가 다시 확인한다."""

import re

TESTED_VALUES = ("yes", "partial", "no", "unclear")
MODES = ("evaluate", "design")
MAX_FIELD_CHARS = 2000

SCENARIO_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["title", "steps", "expected"],
    "properties": {
        "title": {"type": "string"},
        "steps": {"type": "array", "items": {"type": "string"}},
        "expected": {"type": "string"},
    },
}

OUTPUT_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["mode", "summary", "changes", "notes"],
    "properties": {
        "mode": {"type": "string", "enum": list(MODES)},
        "summary": {"type": "string"},
        "changes": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["path", "change_summary", "tested", "evidence_quote", "request", "scenarios"],
                "properties": {
                    "path": {"type": "string"},
                    "change_summary": {"type": "string"},
                    "tested": {"type": "string", "enum": list(TESTED_VALUES)},
                    "evidence_quote": {"type": "string"},
                    "request": {"type": "string"},
                    "scenarios": {"type": "array", "items": SCENARIO_SCHEMA},
                },
            },
        },
        "notes": {"type": "string"},
    },
}


FREE_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["answer"],
    "properties": {"answer": {"type": "string"}},
}

MAX_FREE_CHARS = 6000


class OutputError(Exception):
    """출력 형태가 스키마와 맞지 않을 때 발생한다."""


def _text(value, field):
    if not isinstance(value, str):
        raise OutputError(f"{field}는 문자열이어야 한다")
    return value[:MAX_FIELD_CHARS]


def validate_free(raw):
    """자유 대화 출력 검증. 길이를 제한한 답변 문자열을 돌려준다."""
    if not isinstance(raw, dict) or not isinstance(raw.get("answer"), str):
        raise OutputError("answer가 문자열이 아니다")
    return raw["answer"][:MAX_FREE_CHARS]


def normalize_space(text):
    return " ".join(text.split())


def validate_shape(raw):
    """스키마 모양을 확인하고 길이를 제한한 사본을 돌려준다."""
    if not isinstance(raw, dict):
        raise OutputError("출력이 객체가 아니다")
    if raw.get("mode") not in MODES:
        raise OutputError("mode 값이 잘못되었다")
    changes = raw.get("changes")
    if not isinstance(changes, list):
        raise OutputError("changes가 목록이 아니다")
    clean_changes = []
    for item in changes:
        if not isinstance(item, dict):
            raise OutputError("changes 항목이 객체가 아니다")
        if item.get("tested") not in TESTED_VALUES:
            raise OutputError("tested 값이 잘못되었다")
        scenarios = item.get("scenarios")
        if not isinstance(scenarios, list):
            raise OutputError("scenarios가 목록이 아니다")
        clean_scenarios = []
        for sc in scenarios:
            if not isinstance(sc, dict) or not isinstance(sc.get("steps"), list):
                raise OutputError("scenarios 항목이 잘못되었다")
            clean_scenarios.append({
                "title": _text(sc.get("title"), "scenario.title"),
                "steps": [_text(step, "scenario.step") for step in sc["steps"]][:30],
                "expected": _text(sc.get("expected"), "scenario.expected"),
            })
        clean_changes.append({
            "path": _text(item.get("path"), "path"),
            "change_summary": _text(item.get("change_summary"), "change_summary"),
            "tested": item["tested"],
            "evidence_quote": _text(item.get("evidence_quote"), "evidence_quote"),
            "request": _text(item.get("request"), "request"),
            "scenarios": clean_scenarios[:20],
        })
    return {
        "mode": raw["mode"],
        "summary": _text(raw.get("summary"), "summary"),
        "changes": clean_changes,
        "notes": _text(raw.get("notes"), "notes"),
    }


def postprocess(output, files, qa_text):
    """검증된 출력에 코드 규칙을 적용한다. (결과, 코드가 추가한 메모 목록)을 반환한다."""
    notes = []
    result = dict(output)

    # 서술이 비어 있으면 평가할 대상이 없으므로 설계서 모드로 고정한다.
    if not qa_text.strip() and result["mode"] != "design":
        result["mode"] = "design"
        notes.append("QA 서술이 비어 있어 설계서 모드로 처리했습니다.")

    expected = {f["path"]: f for f in files}
    by_path = {}
    for change in result["changes"]:
        if change["path"] not in expected:
            notes.append("변경 목록에 없는 경로가 분석 결과에 있어 제외했습니다.")
            continue
        if change["path"] in by_path:
            notes.append(f"같은 경로가 중복되어 첫 항목만 사용했습니다: {change['path']}")
            continue
        by_path[change["path"]] = change

    ordered = []
    for path, info in expected.items():
        change = by_path.get(path)
        if change is None:
            notes.append(f"분석 결과에 빠진 파일을 확인 불가로 처리했습니다: {path}")
            change = {
                "path": path, "change_summary": "", "tested": "unclear",
                "evidence_quote": "", "request": "", "scenarios": [],
            }
        if not info.get("diff_included", True):
            if change["tested"] != "unclear":
                notes.append(f"diff가 잘려 내용을 보지 못한 파일을 확인 불가로 처리했습니다: {path}")
            change["tested"] = "unclear"
        ordered.append(change)
    result["changes"] = ordered

    if result["mode"] == "evaluate":
        haystack = normalize_space(qa_text)
        for change in ordered:
            if change["tested"] in ("yes", "partial"):
                quote = normalize_space(change["evidence_quote"])
                if not quote or quote not in haystack:
                    notes.append(f"근거 인용이 QA 서술에 없어 확인 불가로 낮췄습니다: {change['path']}")
                    change["tested"] = "unclear"
                    change["evidence_quote"] = ""
            if change["tested"] != "yes" and not change["request"].strip():
                change["request"] = "이 변경에 대한 테스트를 수행하고 결과를 서술에 추가해 주세요."
    return result, notes


def verdict(result):
    """판정을 코드로 계산한다."""
    if result["mode"] == "design":
        return "design"
    if result["changes"] and all(c["tested"] == "yes" for c in result["changes"]):
        return "sufficient"
    return "more_tests_needed"
