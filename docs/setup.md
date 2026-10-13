# 설치와 설정

이 프로젝트는 Hermes 위에서 동작하는 하위 프로젝트입니다. 개인 설정과 비밀 값은 프로젝트 밖(`$HERMES_HOME`)에 둡니다.
`HERMES_HOME`의 기본값은 호스트에서 `~/.hermes`, Docker 이미지에서 `/opt/data`입니다. 아래 명령은 모두 이 값을 따릅니다.

## 구성

| 위치 | 내용 | 누가 관리하나 |
| --- | --- | --- |
| 이 저장소 `scripts/qa_filter.py` | 웹훅 필터 원본 | 저장소 |
| `$HERMES_HOME/scripts/testgate_qa_filter.py` | 필터 설치본 (복사본) | `scripts/install.sh` |
| `$HERMES_HOME/testgate.json` | 허용 계정 목록 | 사용자 (저장소에 넣지 않음) |
| `$HERMES_HOME/config.yaml` | Hermes 설정 (웹훅 활성화 등) | 사용자 |
| `$HERMES_HOME/webhook_subscriptions.json` | 라우트와 서명 키 | `hermes webhook subscribe` |

필터는 `$HERMES_HOME/scripts/` 안의 파일만 허용됩니다. 심볼릭 링크는 거부되므로 복사합니다.

## 1. 허용 계정 설정

`$HERMES_HOME/testgate.json`을 만듭니다. 이 파일이 없거나 잘못되면 필터는 모든 요청을 버립니다 (fail closed).

```json
{
  "allowed_authors": ["코멘트를 쓸 GitHub 계정"],
  "allowed_repo_owners": ["분석을 허용할 레포 소유자 계정"]
}
```

## 2. 필터 설치

```
scripts/install.sh          # pnpm 없이 사용 가능
scripts/install.sh --check  # 원본과 설치본 비교
```

호스트에서 pnpm을 쓰면 `pnpm filter:install`, `pnpm filter:check`와 같습니다. 필터를 고친 뒤에는 다시 설치합니다.
단위 테스트는 `pnpm filter:test` (또는 `python3 scripts/test_qa_filter.py`)입니다.

## 3. Hermes 웹훅 활성화

`$HERMES_HOME/config.yaml`에 추가합니다.

```yaml
platforms:
  webhook:
    enabled: true
    extra:
      host: 127.0.0.1
      port: 8644
```

Docker에서 `network_mode: host`(기본 compose)이면 호스트의 `127.0.0.1:8644`로 접근합니다. 브리지 네트워크를 쓰면 포트를 열고 `host`를 `0.0.0.0`으로 바꿔야 하며, 외부에 노출하지 않도록 방화벽이나 바인딩 주소를 제한하세요.
설정을 바꾼 뒤 게이트웨이를 재시작합니다 (호스트 systemd: `pnpm gateway:restart:systemd`, Docker: `pnpm gateway:restart:docker` 또는 `docker restart hermes`).

## 4. 라우트 만들기

```
hermes webhook subscribe github-app \
  --events comment \
  --script testgate_qa_filter.py \
  --deliver log \
  --prompt '<분석 프롬프트>'
```

출력되는 secret은 서명 키입니다. 화면에 한 번만 나오므로 안전한 곳에 옮기세요.
이 secret을 github-app의 `.env` 값 `HTTP_SINK_SECRET`에 넣고, `HTTP_SINK_URL`에는 `http://127.0.0.1:8644/webhooks/github-app`을 넣습니다.

## 5. 확인

`docs/mock-test.md`를 따릅니다. 먼저 `pnpm mock:dry`(요청 없음)와 `pnpm mock:safe`(에이전트 없음)를 실행합니다.

## Docker 사용 시 알아 둘 점

- 이미지에는 python3, curl, bash가 있습니다. 필터, 설치 스크립트, mock 도구는 이것만 씁니다. pnpm은 이미지에 없으므로 pnpm 스크립트는 호스트용 편의 기능입니다.
- systemd가 없습니다. 게이트웨이 재시작은 컨테이너 재시작입니다.
- 이후 분석 단계는 Claude Code CLI가 필요합니다. 공식 이미지에서 CLI 설치 여부는 확인하지 못했으며 (Dockerfile에 claude가 보이지 않음), 컨테이너 안에 설치하고 구독 로그인 상태를 볼륨(`$HERMES_HOME`)에 유지하는 방법을 분석 단계에서 정해야 합니다.
