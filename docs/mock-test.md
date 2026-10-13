# mock 테스트 절차

목적: github-app이 보낸 요청이 Hermes에 도착하고, 필터가 `/qa` 코멘트만 통과시키며, 통과한 요청을 래퍼가 분석하는지 확인합니다.
수신 주소: `http://127.0.0.1:8644/webhooks/github-app` (이 PC 안에서만 접근할 수 있습니다).

## 사전 조건

- Hermes 게이트웨이가 실행 중입니다 (`pnpm gateway:status`가 `{"status": "ok", ...}`를 출력).
- 설치와 설정을 마쳤습니다 (`docs/setup.md`). 특히 `$HERMES_HOME/testgate.json`과 필터 설치가 필요합니다.
- 라우트 `github-app`이 `$HERMES_HOME/webhook_subscriptions.json`에 있습니다. mock 도구는 서명 키를 여기서 읽습니다. 키를 출력하거나 공유하지 않습니다.

## 1단계: Hermes 단독 확인 (github-app 없이)

터미널 두 개를 이 저장소 폴더에서 엽니다.

터미널 1: 로그를 봅니다.

```
pnpm gateway:logs
```

터미널 2: 케이스를 실행합니다.

```
pnpm mock:dry     # 요청을 보내지 않고 필터 결과만 출력 (비용 0)
pnpm mock:safe    # 에이전트를 시작하지 않는 5개 케이스를 실제로 전송
pnpm mock:qa      # 에이전트를 시작하는 케이스 (LLM 호출 1회)
pnpm filter:test  # 코멘트 문법 단위 테스트
```

`/qa` 케이스(모두 에이전트를 시작합니다): `mock:qa`, `mock:qa-commit`(`[커밋ID]` 포함), `mock:qa-multiline`(여러 줄), `mock:qa-design`(문서 요청 서술), `mock:qa-empty`(서술 없음), `mock:qa-free`(`/qa free:` 자유 대화), `mock:qa-free-commit`(`/qa free: [커밋ID]`).
실제 PR을 가리키면 Bot 코멘트가 게시됩니다 (`MOCK_REPO`, `MOCK_PR`).

개별 실행: `pnpm mock:plain`, `pnpm mock:other-author`, `pnpm mock:edited`, `pnpm mock:issue`, `pnpm mock:bad-signature`.
상태 확인: `pnpm gateway:status`. 필터를 고친 뒤에는 `pnpm filter:install`로 설치본을 갱신합니다.
pnpm 없이 쓰려면 `scripts/mock_post.sh <케이스>`와 `MOCK_DRY_RUN=1 scripts/mock_post.sh <케이스>`를 직접 실행합니다.

기대 결과:

| 케이스 | 기대 응답 | 로그 | 에이전트 실행 |
| --- | --- | --- | --- |
| plain, other-author, edited, issue | HTTP 200, `"status": "ignored"` | `script ignored` | 없음 |
| bad-signature | HTTP 401, `Invalid signature` | `Invalid signature` | 없음 |
| qa 계열 | HTTP 202, accepted | 세션 시작(LLM은 `OK`만 답함), 래퍼가 별도로 분석 | 있음 (Claude 호출, 세션 LLM 호출 1회) |

주의: `qa` 계열 케이스는 분석을 실제로 실행합니다. Claude 호출 비용이 들고(파일이 많은 PR은 목록가 $0.3 수준), 세션이 하나 만들어지고, `MOCK_REPO`와 `MOCK_PR`로 실제 PR을 가리키면 Bot 코멘트가 게시됩니다.
가짜 레포(기본값)를 가리키면 github-app이 GitHub에서 PR을 찾지 못해 실패 코멘트 경로로 갑니다. 분석까지 보려면 실제 PR을 가리키고, 코멘트를 게시하고 싶지 않으면 `testgate.json`의 `analysis.post_comments`를 잠시 `false`로 둡니다.

## 2단계: github-app 경유 확인

1. github-app의 `.env`에 다음 두 값을 넣습니다.
   - `HTTP_SINK_URL=http://127.0.0.1:8644/webhooks/github-app`
   - `HTTP_SINK_SECRET=` 뒤에 라우트의 secret을 넣습니다. 이미 설정했습니다.
2. `cd ~/github-projects/github-app && pnpm svc:restart`
3. 테스트용 PR에 일반 코멘트를 씁니다 (예: `test`). 최대 약 20초 뒤에 Hermes 로그에 `script ignored`가 나와야 합니다.
4. 같은 PR에 `/qa test` 코멘트를 씁니다. Hermes 로그에 세션이 시작되고(응답 `OK`), 이어서 약 1분 안에 PR에 Bot 코멘트가 달려야 합니다.
5. github-app 로그도 봅니다 (`~/github-projects/github-app`에서 `pnpm svc:logs`). `sink 전송 완료`가 나와야 합니다.

## 문제가 있을 때

- 401: `.env`의 `HTTP_SINK_SECRET`이 라우트의 secret과 다릅니다.
- 아무 로그도 없음: `HTTP_SINK_URL`이 비어 있거나 github-app 재시작을 하지 않았습니다.
- `script ignored`가 `/qa` 코멘트에도 나옴: 코멘트 작성자나 레포 소유자가 `testgate.json`의 허용 목록에 없거나, PR이 아닌 이슈에 쓴 코멘트입니다.
- 로그에 `설정 파일을 읽을 수 없다`가 나옴: `$HERMES_HOME/testgate.json`이 없거나 형식이 잘못되었습니다 (fail closed).
