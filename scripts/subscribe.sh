#!/usr/bin/env bash
# Hermes 웹훅 라우트 'github-app' 을 만들거나 갱신한다.
# 사용법: scripts/subscribe.sh
# - 라우트가 이미 있으면 기존 서명 키를 그대로 쓴다 (키를 바꾸면 github-app 의 HTTP_SINK_SECRET 도 바꿔야 한다).
# - 새로 만들면 Hermes 가 키를 생성하고 화면에 한 번 출력한다.
# - 분석은 필터(testgate_qa_filter.py)가 래퍼를 백그라운드로 시작해서 한다. 세션의 LLM은 분석을 실행하지 않는다.
#   (LLM이 자동화 요청을 보안상 거부하는 경우가 있어 분석이 조용히 사라졌기 때문이다.)
#   그래서 이 라우트의 세션에는 도구를 주지 않는다. 세션은 요청의 기록으로 남고 래퍼가 이름을 붙인다.
# HERMES_HOME 기본값은 ~/.hermes 이다 (Docker 이미지는 /opt/data).
set -euo pipefail

HERMES_HOME="${HERMES_HOME:-$HOME/.hermes}"
ROUTE="${ROUTE:-github-app}"
SUBS="$HERMES_HOME/webhook_subscriptions.json"
LAUNCHER="$HERMES_HOME/testgate/testgate-run"
[ -x "$LAUNCHER" ] || { echo "래퍼가 없다. 먼저 scripts/install.sh 를 실행한다: $LAUNCHER" >&2; exit 1; }

PROMPT="QA request {deliveryId} for {event.repo.fullName} PR #{event.number} was received. A background job analyzes it and posts the result by itself. Reply with exactly the single word: OK. Do not use any tool."

ARGS=(webhook subscribe "$ROUTE"
  --events comment
  --script testgate_qa_filter.py
  --deliver log
  --description "github-app sink: PR /qa comment -> testgate analysis"
  --prompt "$PROMPT")

EXISTING="$(ROUTE="$ROUTE" SUBS="$SUBS" python3 -c 'import json,os;print(json.load(open(os.environ["SUBS"]))[os.environ["ROUTE"]]["secret"])' 2>/dev/null || true)"
if [ -n "$EXISTING" ]; then
  ARGS+=(--secret "$EXISTING")
  hermes "${ARGS[@]}" | sed "s/$EXISTING/<기존 secret 유지>/g"
else
  hermes "${ARGS[@]}"
fi

# 이전 방식이 남긴 terminal 도구 허용이 있으면 지운다 (Hermes 설계상 CLI 로는 바꿀 수 없어 JSON 을 직접 고친다).
ROUTE="$ROUTE" SUBS="$SUBS" python3 - <<'PY'
import json, os
path, route = os.environ["SUBS"], os.environ["ROUTE"]
data = json.load(open(path, encoding="utf-8"))
removed = data[route].pop("toolsets", None)
tmp = path + ".tmp"
with open(tmp, "w", encoding="utf-8") as handle:
    json.dump(data, handle, ensure_ascii=False, indent=2)
os.chmod(tmp, 0o600)
os.replace(tmp, path)
print("toolsets 제거: " + str(removed) if removed else "toolsets 없음 (세션에 도구를 주지 않음)")
PY
echo "라우트는 다음 요청부터 바로 적용된다 (게이트웨이 재시작 불필요)."
