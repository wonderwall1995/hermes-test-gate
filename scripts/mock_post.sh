#!/usr/bin/env bash
# Hermes 웹훅 라우트에 가짜 github-app 요청을 보낸다.
# 사용법: scripts/mock_post.sh <케이스>
# 케이스: qa | qa-commit | qa-multiline | qa-design | qa-empty | plain | other-author | edited | issue | bad-signature
# MOCK_DRY_RUN=1 이면 요청을 보내지 않고 필터 스크립트(scripts/qa_filter.py)의 결과만 출력한다. 에이전트를 실행하지 않는다.
# HERMES_HOME 기본값은 ~/.hermes 이다 (Docker 이미지는 /opt/data).
# 서명 키는 $HERMES_HOME/webhook_subscriptions.json 의 라우트 설정에서 읽는다. 키를 화면에 출력하지 않는다.
# 작성자와 레포 소유자는 $HERMES_HOME/testgate.json 의 첫 번째 허용 계정을 쓴다 (MOCK_AUTHOR, MOCK_OWNER 로 바꿀 수 있다).
set -euo pipefail

CASE="${1:-}"
HERMES_HOME="${HERMES_HOME:-$HOME/.hermes}"
URL="${MOCK_URL:-http://127.0.0.1:8644/webhooks/github-app}"
SUBS_FILE="${MOCK_SUBS_FILE:-$HERMES_HOME/webhook_subscriptions.json}"
CONFIG_FILE="${TESTGATE_CONFIG:-$HERMES_HOME/testgate.json}"
export TESTGATE_CONFIG="$CONFIG_FILE"
ROUTE="${MOCK_ROUTE:-github-app}"
SECRET="$(python3 -c 'import json,sys;print(json.load(open(sys.argv[1]))[sys.argv[2]]["secret"])' "$SUBS_FILE" "$ROUTE" 2>/dev/null)" \
  || { echo "라우트 '$ROUTE'의 secret을 읽을 수 없다: $SUBS_FILE" >&2; exit 2; }

BODY_TEXT="/qa 로그를 확인했고 다른 테스트는 하지 않았다"
first_allowed() { python3 -c 'import json,sys;print(json.load(open(sys.argv[1]))[sys.argv[2]][0])' "$CONFIG_FILE" "$1" 2>/dev/null; }
AUTHOR="${MOCK_AUTHOR:-$(first_allowed allowed_authors)}"
OWNER="${MOCK_OWNER:-$(first_allowed allowed_repo_owners)}"
[ -n "$AUTHOR" ] && [ -n "$OWNER" ] || { echo "허용 계정을 읽을 수 없다: $CONFIG_FILE (MOCK_AUTHOR, MOCK_OWNER 로 지정할 수 있다)" >&2; exit 2; }
ACTION="created"
TARGET="pull_request"
case "$CASE" in
  qa) ;;
  qa-commit) BODY_TEXT="/qa [abc1421511] 나는 로그를 확인해봤고 테스트는 더 진행하지 않았지." ;;
  qa-multiline) BODY_TEXT=$'/qa [abc1421511] 첫 줄 서술\n\n- 로그 확인: 통과\n- 모킹 여부: 확인함\n\n"따옴표"와 \\ 역슬래시도 포함' ;;
  qa-design) BODY_TEXT="/qa 야 나 솔직히 테스트 뭐해야할지 모르겠는데 네가 문서좀 뽑아봐" ;;
  qa-empty) BODY_TEXT="/qa" ;;
  plain) BODY_TEXT="looks good to me" ;;
  other-author) AUTHOR="someone-else" ;;
  edited) ACTION="edited" ;;
  issue) TARGET="issue" ;;
  bad-signature) ;;
  *) echo "알 수 없는 케이스: '$CASE'" >&2; exit 2 ;;
esac

DELIVERY="mock-$(date +%s)-$RANDOM"
BODY="$(DELIVERY="$DELIVERY" OWNER="$OWNER" ACTION="$ACTION" TARGET="$TARGET" AUTHOR="$AUTHOR" BODY_TEXT="$BODY_TEXT" python3 -c '
import json, os
e = os.environ
print(json.dumps({"deliveryId": e["DELIVERY"], "event": {
    "kind": "comment", "action": e["ACTION"], "target": e["TARGET"], "number": 1, "commentId": 1,
    "url": "https://example.invalid/mock",
    "repo": {"owner": e["OWNER"], "name": "hermes-test-gate", "fullName": e["OWNER"] + "/hermes-test-gate"},
    "author": {"login": e["AUTHOR"], "type": "User"}, "body": e["BODY_TEXT"]}}, ensure_ascii=False))
')"

if [ "${MOCK_DRY_RUN:-}" = "1" ]; then
  echo "케이스: $CASE (DRY RUN, 요청을 보내지 않음)"
  RESULT="$(printf '%s' "$BODY" | python3 "$(dirname "$0")/qa_filter.py")"
  if [ -z "$RESULT" ]; then echo "필터 결과: 버림"; else printf '필터 결과: %s\n' "$RESULT"; fi
  exit 0
fi

if [ "$CASE" = "bad-signature" ]; then
  SIG="sha256=$(printf '0%.0s' $(seq 1 64))"
else
  SIG="sha256=$(SECRET="$SECRET" BODY="$BODY" python3 -c 'import hmac,hashlib,os;print(hmac.new(os.environ["SECRET"].encode(),os.environ["BODY"].encode(),hashlib.sha256).hexdigest())')"
fi

echo "케이스: $CASE  delivery: $DELIVERY"
curl -sS -m 10 -o /dev/stdout -w '\nHTTP %{http_code}\n' -X POST "$URL" \
  -H 'content-type: application/json' \
  -H "x-github-delivery: $DELIVERY" \
  -H 'x-github-event: comment' \
  -H "x-hub-signature-256: $SIG" \
  --data "$BODY"
