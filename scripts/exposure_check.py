"""노출 회귀 확인: 실제 Claude로 분석한 보고서에 참고 문서(CED)의 내용이 나오지 않는지 본다.

사용법: python3 scripts/exposure_check.py [--context 맥락파일] [--diff diff파일] [--description 설명파일]
기본값은 contracts/context.v1.json 과 내장 예시 PR이다. 실제 Claude(claude -p)를 부르므로 구독 사용량이 든다.
GitHub에는 아무것도 게시하지 않는다. 프롬프트를 고치거나 모델을 바꾼 뒤 손으로 돌린다.

판정: 문서의 제목, 문서 ID, 본문의 긴 문장(12자 이상) 중 하나라도 보고서에 그대로 나오면 실패(종료 코드 1).
"""

import argparse
import json
import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from testgate import analyze, contextfile, runner  # noqa: E402

SAMPLE_DIFF = """diff --git a/src/report.py b/src/report.py
--- a/src/report.py
+++ b/src/report.py
@@ -10,3 +10,3 @@ def total_balance(accounts):
-    total = sum(a.balance for a in accounts)
+    total = sum(a.balance for a in accounts if a.balance > 0)
     return total
"""


def leaks(markdown, docs):
    found = []
    for doc in docs:
        for probe in [doc["id"], doc["title"]] + [s.strip() for s in re.split(r"[\n.]", doc["text"]) if len(s.strip()) >= 12]:
            if probe and probe in markdown:
                found.append(probe)
    return found


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--context", default=str(ROOT / "contracts" / "context.v1.json"))
    parser.add_argument("--diff")
    parser.add_argument("--description", default="합계 로직을 고쳤다.")
    parser.add_argument("--text", default="", help="QA 서술 (비우면 설계서 모드)")
    args = parser.parse_args(argv)
    diff = pathlib.Path(args.diff).read_text(encoding="utf-8") if args.diff else SAMPLE_DIFF
    paths = sorted(set(re.findall(r"^\+\+\+ b/(.+)$", diff, re.M)))
    context = {"title": "확인용 PR", "body": args.description, "base_ref": "main", "scope": "pr", "head_sha": "0" * 7,
               "files": [{"path": p, "status": "modified", "additions": 1, "deletions": 1, "diff_included": True} for p in paths],
               "diff": diff, "truncated": False}
    request = {"deliveryId": "exposure-check", "repo": "local/check", "pr": 1, "commit": None, "text": args.text}
    kb = contextfile.ContextFileKnowledge(args.context)
    docs = kb.load(context)
    kb = contextfile.ContextFileKnowledge(args.context)
    out = analyze.analyze(request, context, kb, runner.ClaudeRunner())
    found = leaks(out["markdown"], docs)
    print(json.dumps({"docs": len(docs), "leaks": found}, ensure_ascii=False))
    return 1 if found else 0


if __name__ == "__main__":
    sys.exit(main())
