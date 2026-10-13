#!/usr/bin/env bash
# 필터 스크립트를 Hermes가 허용하는 위치($HERMES_HOME/scripts)에 복사한다.
# 사용법: scripts/install.sh [--check]
#   --check : 복사하지 않고 원본과 설치본이 같은지만 확인한다.
# HERMES_HOME 기본값은 ~/.hermes 이다. Docker 이미지에서는 /opt/data 이다.
# 이 스크립트는 pnpm 없이 동작한다.
set -euo pipefail

HERMES_HOME="${HERMES_HOME:-$HOME/.hermes}"
SRC="$(cd "$(dirname "$0")" && pwd)/qa_filter.py"
DEST_DIR="$HERMES_HOME/scripts"
DEST="$DEST_DIR/testgate_qa_filter.py"

if [ "${1:-}" = "--check" ]; then
  diff -q "$SRC" "$DEST" >/dev/null && echo "원본과 설치본이 같다: $DEST" || { echo "원본과 설치본이 다르거나 설치본이 없다: $DEST" >&2; exit 1; }
  exit 0
fi

mkdir -p "$DEST_DIR"
cp -p "$SRC" "$DEST"
echo "필터 스크립트를 복사했다: $DEST"
if [ ! -r "$HERMES_HOME/testgate.json" ]; then
  echo "주의: $HERMES_HOME/testgate.json 이 없다. 설정 파일이 없으면 필터가 모든 요청을 버린다 (docs/setup.md 참고)." >&2
fi
