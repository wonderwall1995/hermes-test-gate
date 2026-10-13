# 설치와 설정

이 프로젝트는 Hermes 위에서 동작하는 하위 프로젝트입니다. 개인 설정과 비밀 값은 프로젝트 밖(`$HERMES_HOME`)에 둡니다.
`HERMES_HOME`의 기본값은 호스트에서 `~/.hermes`, Docker 이미지에서 `/opt/data`입니다. 아래 명령은 모두 이 값을 따릅니다.

## 구성

| 위치 | 내용 | 누가 관리하나 |
| --- | --- | --- |
| 이 저장소 `scripts/qa_filter.py` | 웹훅 필터 원본 | 저장소 |
| `$HERMES_HOME/scripts/testgate_qa_filter.py` | 필터 설치본 (복사본) | `scripts/install.sh` |
| `$HERMES_HOME/testgate/lib/testgate/` | 분석기 패키지 설치본 | `scripts/install.sh` |
| `$HERMES_HOME/testgate/testgate-run` | 필터가 백그라운드로 시작하는 래퍼 (인자: delivery ID) | `scripts/install.sh` |
| `$HERMES_HOME/testgate/requests/`, `reports/`, `threads/` | 필터가 저장한 요청, 분석 보고서, PR 대화 기록 (30일 뒤 자동 삭제) | 자동 |
| `$HERMES_HOME/testgate.json` | 허용 계정과 분석 설정 (비밀 아님) | 사용자 (저장소에 넣지 않음) |
| `$HERMES_HOME/.env` | 비밀 값 (Hermes의 자격 증명 저장소). 필요한 이름은 저장소의 `.env.example` | 사용자 (이 프로젝트는 읽거나 쓰지 않음) |
| `$HERMES_HOME/config.yaml` | Hermes 설정 (웹훅 활성화 등) | 사용자 |
| `$HERMES_HOME/webhook_subscriptions.json` | 라우트와 서명 키 | `hermes webhook subscribe` |

필터는 `$HERMES_HOME/scripts/` 안의 파일만 허용됩니다. 심볼릭 링크는 거부되므로 복사합니다.

`$HERMES_HOME`은 여러 프로젝트가 함께 쓰므로, 이 저장소가 설치하는 파일의 맨 아래에는 `[hermes-test-gate] 현재 Repo(hermes-test-gate)로 생성한 파일입니다.` 표시가 붙습니다. 다른 프로젝트의 파일과 구분하는 용도이며, 그 표시가 있는 파일은 직접 고치지 않고 `scripts/install.sh`로 다시 설치합니다.

## 1. 허용 계정 설정

`$HERMES_HOME/testgate.json`을 만듭니다. 이 파일이 없거나 잘못되면 필터는 모든 요청을 버립니다 (fail closed).

```json
{
  "allowed_authors": ["코멘트를 쓸 GitHub 계정"],
  "allowed_repo_owners": ["분석을 허용할 레포 소유자 계정"]
}
```

선택 항목 `analysis`로 분석기를 조정합니다 (필터는 이 항목을 읽지 않습니다).

```json
{
  "allowed_authors": ["..."],
  "allowed_repo_owners": ["..."],
  "analysis": {
    "claude_model": "claude-sonnet-5-5",
    "claude_effort": "medium",
    "timeout_seconds": 150,
    "max_diff_chars": 120000,
    "knowledge_dirs": [],
    "github_app_url": "http://127.0.0.1:3200",
    "post_comments": true,
    "route_name": "github-app",
    "hermes_binary": "hermes",
    "retention_days": 30
  }
}
```

### 비밀 값

이 프로젝트는 비밀을 저장하거나 파일에서 읽지 않습니다. 필요한 비밀의 이름만 저장소의 `.env.example`에 있고 값은 없습니다. 값은 Hermes 실행 환경이 환경 변수로 넘깁니다.

1. 호스트: `~/.hermes/.env`에 `TESTGATE_GITHUB_APP_SECRET=<값>`을 적습니다. 값은 github-app의 `.env`에 있는 `HERMES_API_SECRET`과 같습니다.
   Docker: 컨테이너 환경 변수로 같은 이름을 넘깁니다.
2. Hermes는 하위 프로세스(필터 스크립트와 터미널 도구)에서 자신의 비밀을 걸러 내므로, `config.yaml`에 이름을 등록해 넘기게 합니다.

```yaml
terminal:
  env_passthrough:
    - TESTGATE_GITHUB_APP_SECRET
```

3. 게이트웨이를 재시작합니다 (`.env`와 `config.yaml`을 다시 읽도록).

`claude_effort`는 `low`, `medium`, `high`, `xhigh`, `max` 중 하나입니다. 모델을 지정하지 않으면 Claude Code의 기본 모델(Opus)이 쓰여 비용이 큽니다.

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
scripts/subscribe.sh          # pnpm route:subscribe
```

라우트 `github-app`을 만들거나 갱신합니다. 이 스크립트는 다음을 합니다.
- 이벤트는 `comment`만 받고, `testgate_qa_filter.py` 필터를 거칩니다.
- 분석은 필터가 래퍼(`testgate-run`)를 백그라운드로 시작해서 합니다. 필터는 요청을 파일(`requests/`)로 저장하고 곧바로 끝나므로 Hermes의 스크립트 제한(30초)에 걸리지 않습니다.
- Hermes 세션의 LLM은 분석을 실행하지 않습니다. 세션은 요청의 기록으로 남고, 래퍼가 끝날 때 상태 DB에서 `chat_id`로 세션을 찾아 이름을 붙입니다. 세션에는 도구를 주지 않습니다.
- 필터가 호출하는 래퍼가 서명 키를 받으려면 `terminal.env_passthrough` 등록이 필요합니다 (아래 비밀 값 참고).
- 이미 라우트가 있으면 기존 서명 키를 유지합니다. 새로 만들면 Hermes가 키를 한 번 출력하니 안전한 곳에 옮기세요.

github-app의 `.env`에는 두 종류의 키가 필요합니다. 서로 다른 값입니다.
- `HTTP_SINK_SECRET`: github-app이 Hermes로 보내는 요청의 서명 키. 위 라우트의 키와 같아야 합니다. `HTTP_SINK_URL`은 `http://127.0.0.1:8644/webhooks/github-app`.
- `HERMES_API_SECRET`: Hermes가 github-app의 조회, 게시 API를 부를 때의 서명 키. Hermes 쪽 `TESTGATE_GITHUB_APP_SECRET`과 같아야 합니다.

## 5. 확인

`docs/mock-test.md`를 따릅니다. 먼저 `pnpm mock:dry`(요청 없음)와 `pnpm mock:safe`(에이전트 없음)를 실행합니다.

## Docker 사용 시 알아 둘 점

- 이미지에는 python3, curl, bash가 있습니다. 필터, 설치 스크립트, mock 도구는 이것만 씁니다. pnpm은 이미지에 없으므로 pnpm 스크립트는 호스트용 편의 기능입니다.
- systemd가 없습니다. 게이트웨이 재시작은 컨테이너 재시작입니다.
- 분석에는 Claude Code CLI가 필요합니다. 공식 이미지에서 CLI 설치 여부는 확인하지 못했으며 (Dockerfile에 claude가 보이지 않음), 컨테이너 안에 설치하고 구독 로그인 상태를 볼륨(`$HERMES_HOME`)에 유지하는 방법을 정해야 합니다.
- 필터가 래퍼를 백그라운드 프로세스로 띄웁니다. 컨테이너에서 이 프로세스가 끝까지 살아 있는지는 호스트에서만 확인했고 Docker에서는 시험하지 않았습니다.
- 분석 중에 게이트웨이(컨테이너)를 재시작하면 그 건의 분석은 끊깁니다.
