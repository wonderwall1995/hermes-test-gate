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
#   $HERMES_HOME/testgate/testgate-run           필터가 백그라운드로 시작하는 래퍼 (인자: delivery ID)
#   $HERMES_HOME/testgate/README.md              Hermes가 읽는 안내 문서 (원본: docs/hermes-guide.md)
# 설치하는 파일의 맨 아래에는 '현재 Repo로 생성한 파일' 표시를 붙인다. $HERMES_HOME 을 여러 프로젝트가 같이 쓰므로 출처를 구분하기 위해서다.
#   $HERMES_HOME/testgate/config.path            설정 파일(저장소의 testgate.json)의 경로를 적은 안내 파일
# 이 스크립트가 만들거나 덮어쓰지 않는 사용자 파일:
#   <저장소>/testgate.json       허용 계정과 분석 설정 (비밀 없음, git 에는 올리지 않음). 예시는 testgate.example.json
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

# 마크다운 문서용. 마크다운에는 주석이 없어 눈에 보이지 않는 HTML 주석으로 표시한다.
put_md() {
  local src="$1" dest="$2"
  mkdir -p "$(dirname "$dest")"
  { cat "$src"; printf '\n<!-- %s -->\n' "$MARK"; } > "$dest"
}

# $1 아래에 설치될 파일 전체를 만든다. $HERMES_HOME 문자열은 래퍼에 들어가는 값이다.
render() {
  local out="$1"
  put "$HERE/qa_filter.py" "$out/scripts/testgate_qa_filter.py"
  (cd "$REPO/testgate" && find . -name '*.py' -print0) | while IFS= read -r -d '' f; do
    put "$REPO/testgate/$f" "$out/testgate/lib/testgate/$f"
  done
  put_md "$REPO/docs/hermes-guide.md" "$out/testgate/README.md"
  mkdir -p "$out/testgate"
  # 설정 파일은 저장소 안에 있다. 설치된 코드는 이 안내 파일로 그 위치를 찾는다 (주석 줄은 읽을 때 무시한다).
  printf '%s\n\n# %s\n' "$REPO/testgate.json" "$MARK" > "$out/testgate/config.path"
  cat > "$out/testgate/testgate-run" <<LAUNCH
#!/usr/bin/env bash
export HERMES_HOME="$HERMES_HOME"
export PYTHONPATH="$HERMES_HOME/testgate/lib\${PYTHONPATH:+:\$PYTHONPATH}"
# 필터가 이 파일을 표준 입출력 없이 띄우므로 출력과 오류를 로그 파일로 보낸다. 안 그러면 실패가 흔적 없이 사라진다.
LOG_DIR="\$HERMES_HOME/logs"
LOG="\$LOG_DIR/testgate.log"
# 로그도 다른 데이터 파일처럼 소유자만 읽게 한다.
umask 077
mkdir -p "\$LOG_DIR" 2>/dev/null
# 로그가 1MB를 넘으면 한 세대만 남기고 새로 시작한다.
if [ -f "\$LOG" ] && [ "\$(wc -c < "\$LOG")" -gt 1048576 ]; then mv -f "\$LOG" "\$LOG.1" 2>/dev/null; fi
# 로그 파일을 쓸 수 없으면 버린다. 로그 때문에 분석이 멈추면 안 된다.
if ! : >> "\$LOG" 2>/dev/null; then LOG=/dev/null; fi
exec python3 -m testgate run "\$@" >> "\$LOG" 2>&1

# $MARK
LAUNCH
  chmod 755 "$out/testgate/testgate-run"
}

if [ "${1:-}" = "--check" ]; then
  tmp="$(mktemp -d)"
  trap 'rm -rf "$tmp"' EXIT
  render "$tmp"
  status=0
  for path in scripts/testgate_qa_filter.py testgate/lib/testgate testgate/testgate-run testgate/README.md testgate/config.path; do
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
echo "  안내   $HERMES_HOME/testgate/README.md"
echo "  설정   $REPO/testgate.json (경로를 $HERMES_HOME/testgate/config.path 에 적음)"
if [ ! -r "$REPO/testgate.json" ]; then
  echo "주의: $REPO/testgate.json 이 없다. 설정 파일이 없으면 필터가 모든 요청을 버린다. testgate.example.json 을 복사해 채우세요 (docs/setup.md 참고)." >&2
fi
if [ -r "$HERMES_HOME/testgate.json" ]; then
  echo "주의: 옛 위치 $HERMES_HOME/testgate.json 이 남아 있다. 이제 쓰지 않으므로 내용을 $REPO/testgate.json 으로 옮기고 지우세요." >&2
fi
