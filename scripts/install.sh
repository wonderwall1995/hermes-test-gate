#!/usr/bin/env bash
# 필터와 분석기를 Hermes가 쓰는 위치($HERMES_HOME)에 설치한다.
# 사용법: scripts/install.sh [--check]
#   --check : 설치하지 않고 원본과 설치본이 같은지만 확인한다.
# HERMES_HOME 기본값은 ~/.hermes 이다. Docker 이미지에서는 /opt/data 이다.
# 이 스크립트는 pnpm 없이 동작한다.
#
# 설치 위치:
#   $HERMES_HOME/scripts/testgate_qa_filter.py   웹훅 라우트 필터 (Hermes가 이 폴더만 허용한다)
#   $HERMES_HOME/testgate/lib/testgate/          분석기 패키지
#   $HERMES_HOME/testgate/testgate-run           세션이 실행하는 래퍼 (인자: delivery ID)
# 설치하는 파일의 맨 아래에는 '현재 Repo로 생성한 파일' 표시를 붙인다. $HERMES_HOME 을 여러 프로젝트가 같이 쓰므로 출처를 구분하기 위해서다.
# 이 스크립트가 만들거나 덮어쓰지 않는 사용자 파일 (비밀과 설정은 프로젝트 밖에서 사용자가 관리한다):
#   $HERMES_HOME/testgate.json   허용 계정과 분석 설정 (비밀 없음)
#   비밀 값은 Hermes 의 환경(.env 또는 컨테이너 환경 변수)으로 넘긴다. 필요한 이름은 저장소의 .env.example 에 있다.
set -euo pipefail

HERMES_HOME="${HERMES_HOME:-$HOME/.hermes}"
HERE="$(cd "$(dirname "$0")" && pwd)"
REPO="$(cd "$HERE/.." && pwd)"
MARK="[hermes-test-gate] 현재 Repo(hermes-test-gate)로 생성한 파일입니다. 직접 고치지 않고 저장소의 scripts/install.sh 로 다시 설치합니다."

# 원본 파일에 표시를 붙여 대상에 쓴다. 실행 권한은 원본을 따른다.
put() {
  local src="$1" dest="$2"
  mkdir -p "$(dirname "$dest")"
  { cat "$src"; printf '\n# %s\n' "$MARK"; } > "$dest"
  chmod "$(stat -c %a "$src")" "$dest"
}

# $1 아래에 설치될 파일 전체를 만든다. $HERMES_HOME 문자열은 래퍼에 들어가는 값이다.
render() {
  local out="$1"
  put "$HERE/qa_filter.py" "$out/scripts/testgate_qa_filter.py"
  (cd "$REPO/testgate" && find . -name '*.py' -print0) | while IFS= read -r -d '' f; do
    put "$REPO/testgate/$f" "$out/testgate/lib/testgate/$f"
  done
  mkdir -p "$out/testgate"
  cat > "$out/testgate/testgate-run" <<LAUNCH
#!/usr/bin/env bash
export HERMES_HOME="$HERMES_HOME"
export PYTHONPATH="$HERMES_HOME/testgate/lib\${PYTHONPATH:+:\$PYTHONPATH}"
exec python3 -m testgate run "\$@"

# $MARK
LAUNCH
  chmod 755 "$out/testgate/testgate-run"
}

if [ "${1:-}" = "--check" ]; then
  tmp="$(mktemp -d)"
  trap 'rm -rf "$tmp"' EXIT
  render "$tmp"
  status=0
  for path in scripts/testgate_qa_filter.py testgate/lib/testgate testgate/testgate-run; do
    diff -rq -x __pycache__ "$tmp/$path" "$HERMES_HOME/$path" >/dev/null 2>&1 || { echo "원본과 다르거나 없다: $HERMES_HOME/$path" >&2; status=1; }
  done
  [ "$status" = 0 ] && echo "원본과 설치본이 같다 (HERMES_HOME=$HERMES_HOME)"
  exit "$status"
fi

mkdir -p "$HERMES_HOME/scripts" "$HERMES_HOME/testgate"
rm -rf "$HERMES_HOME/testgate/lib/testgate"
render "$HERMES_HOME"

echo "설치했다:"
echo "  필터   $HERMES_HOME/scripts/testgate_qa_filter.py"
echo "  패키지 $HERMES_HOME/testgate/lib/testgate"
echo "  래퍼   $HERMES_HOME/testgate/testgate-run"
if [ ! -r "$HERMES_HOME/testgate.json" ]; then
  echo "주의: $HERMES_HOME/testgate.json 이 없다. 설정 파일이 없으면 필터가 모든 요청을 버린다 (docs/setup.md 참고)." >&2
fi
