# llms-todo

hermes-test-gate (가제: testgate)의 작업 목록입니다.
이 파일은 LLM이 관리합니다. 기획 원문은 github-app 레포의 `readonly-todo.md`(사용자 전용, 수정 금지)입니다.
상태 표기: [ ] 미착수, [?] 결정 필요, [x] 완료.

## 목표

QA가 커밋 또는 PR에 테스트 체크리스트를 자연어로 제출합니다.
Hermes가 해당 diff를 가져옵니다. Hermes 하위 Claude Code가 읽기 전용으로 실행되어, QA가 적절한 커버리지 안에서 테스트했는지 평가합니다. 결과는 PR 코멘트 또는 Slack으로 돌려줍니다.

## 전체 흐름

```
GitHub
  -> Cloudflare Worker (github-app-gate: 서명 검증, 중복 제거, D1 보관)
  <- 노트북의 github-app (20초 간격 pull, ack 후 삭제)
  -> SinkRouter -> HttpSink (HTTP_SINK_URL)
  -> Hermes 웹훅 게이트웨이 (localhost, /webhooks/<route>)
  -> [본 레포] diff 수집 -> Claude Code 평가 -> 결과 게시
```

## 역할 분담

| 구분 | 담당 | 범위 |
| --- | --- | --- |
| 이벤트 수집과 전달 | github-app 레포 | Worker, 정규화, Sink. 대부분 완료 |
| 웹훅 수신과 라우팅 | Hermes 코어 설정 | `config.yaml`, `hermes webhook subscribe`. 코어 코드 수정 없음 |
| diff 수집, 평가, 게시 | 본 레포 (testgate) | 아래 "본 레포 작업" |
| GitHub, Slack 설정 | 사용자 | 아래 "사용자 작업" |

## 확인된 사실 (2026-10-12 코드 확인)

- Hermes 웹훅 수신: `hermes-agent/gateway/platforms/webhook.py`. 경로는 `POST /webhooks/{route_name}`입니다.
- Hermes 라우트 설정: `events`, `secret`(필수), `prompt` 템플릿, `skills`, `deliver`, `deliver_extra`, `script`. `hermes webhook subscribe`로 생성합니다.
- Hermes 서명 검증이 인식하는 헤더: `X-Hub-Signature-256`, `X-Webhook-Signature-V2`(+`X-Webhook-Timestamp`), `X-Webhook-Signature`(구형), GitLab, Linear, Svix.
- 이 PC의 현재 상태: `config.yaml`에 webhook 설정이 없고 구독 파일도 없습니다. 웹훅 수신은 꺼져 있습니다.
- Hermes `project` 기능(`hermes project create`)은 `projects.db`에 폴더를 등록할 뿐입니다. 웹훅 라우트와 연결되지 않습니다. `~/.hermes/projects/` 폴더도 Hermes가 자동 인식하지 않습니다.
- Hermes에는 `skills/github/` 아래에 `github-code-review`, `github-pr-workflow`, `github-issue-to-pr`가 이미 있습니다. 재사용 여부를 먼저 검토합니다.

## 연동 차단 요인 (github-app 쪽 수정 필요)

github-app의 `src/sinks/http.ts`가 보내는 요청을 Hermes가 현재 거부합니다.

1. 서명 헤더 불일치: github-app은 `X-Signature-256`을 보냅니다. Hermes는 이 이름을 인식하지 않아 401을 반환합니다.
   - 선택지 A: 헤더를 `X-Hub-Signature-256`으로 변경합니다 (값 형식 `sha256=<hex>`는 이미 같습니다).
   - 선택지 B: `X-Webhook-Signature-V2`와 `X-Webhook-Timestamp`를 사용합니다. 재전송 공격을 막을 수 있습니다.
2. 이벤트 종류 불일치: github-app 본문은 `{deliveryId, event:{kind,...}}`이고 `X-GitHub-Event` 헤더가 없습니다. Hermes는 이벤트를 항상 `unknown`으로 분류합니다. 라우트에 `events` 필터를 걸면 모든 요청이 무시됩니다.
   - 선택지: `X-GitHub-Event` 헤더를 추가합니다. 값은 `event.kind`에서 만듭니다. 또는 본문 최상위에 `type`을 추가합니다.

권장: 선택지 B와 `X-GitHub-Event` 추가. 결정은 [?] 상태입니다.

## 본 레포 작업 (testgate)

### 결정 필요

- [?] 구현 형태: Hermes 스킬, 웹훅 라우트의 `script`, 플러그인, 독립 CLI 중 선택합니다. 이 레포는 하위 프로젝트(서브 모듈 유사)로 정의되어 있습니다. Hermes 방침은 "코어 수정 금지, 스킬 또는 플러그인 우선"입니다.
- [?] QA 체크리스트 제출 형식: PR 코멘트 `/qa <sha>` 형식을 제안합니다 (github-app의 llms-todo 5번과 동일).
- [?] 평가 모드: `commit`(커밋 하나의 diff) 또는 `pr`(PR 전체 커밋의 diff). 둘 다 지원할지 결정합니다.
- [?] 결과 게시 위치: PR 코멘트, Slack, 또는 둘 다.
- [?] 판정 기준: 합격 임계값과 "테스트 커버리지 충족"의 정의. 변경된 코드 라인 대비 체크리스트 항목 매핑으로 판단할지, CI 커버리지 리포트도 사용할지 정합니다.

### 구현

- [ ] 레포 기본 문서: CLAUDE.md 작성 (세션 규칙, 구조)
- [ ] QA 체크리스트 파서: 코멘트 본문에서 sha, 항목 목록 추출
- [ ] diff 수집 모듈: `gh` CLI 또는 GitHub API로 커밋 diff와 PR diff 수집. 큰 diff는 파일별로 분할하고 요약 폴백을 둡니다.
- [ ] 저장소 접근: 대상 레포를 로컬에 클론하는 위치와 정리 규칙. 임시 worktree 사용을 권장합니다.
- [ ] Claude Code 헤드리스 실행기: OAuth 구독 로그인 사용, 읽기 전용 도구만 허용, 네트워크 차단.
- [ ] 평가 프롬프트와 JSON 출력 스키마: 판정, 점수, 누락 항목.
- [ ] 프롬프트 인젝션 방어: diff와 체크리스트를 비신뢰 입력으로 취급합니다. 출력 스키마를 검증합니다.
- [ ] 결과 게시: GitHub 코멘트 또는 Slack 답장. 게시 전 결과 형식을 검증합니다.
- [ ] 중복 처리: `deliveryId` 기준 멱등 처리 (github-app은 실패 시 성공한 sink에도 재전송합니다).
- [ ] 오류 처리: 실패, 재시도, 타임아웃, 로깅.
- [ ] 테스트: mock 이벤트로 end-to-end 확인.

## Hermes 설정 작업 (코어 코드 수정 없음)

- [ ] `config.yaml`에서 webhook 플랫폼 활성화. 포트와 바인딩 주소는 localhost로 제한합니다.
- [ ] `hermes webhook subscribe`로 라우트 생성 (이벤트 필터, 프롬프트, 스킬, deliver 지정).
- [ ] 라우트 secret을 github-app의 `HTTP_SINK_SECRET`과 동일하게 맞춥니다. 값은 문서나 저장소에 기록하지 않습니다.
- [ ] `hermes gateway run`으로 게이트웨이가 실행 중인지 확인합니다. 현재 `gateway.pid`는 있으나 webhook 활성화 여부는 미확인입니다.
- [ ] `hermes project create`로 본 레포 등록 (선택, 세션 그룹핑 용도).

## github-app 레포 작업 (별도 세션, 해당 레포의 규칙을 따름)

- [ ] `src/sinks/http.ts` 서명 헤더와 이벤트 종류 헤더 호환 수정 (위 "연동 차단 요인").
- [ ] `.env`의 `HTTP_SINK_URL`을 Hermes 수신 주소로 설정합니다 (예: `http://127.0.0.1:<포트>/webhooks/<route>`).
- [ ] 허용 목록 구현: `ALLOWED_REPOS`, `ALLOWED_ACTORS`. 본인 레포와 본인 계정의 이벤트만 Hermes로 전달합니다. (llms-todo 7번)
- [ ] 필요하면 Sink의 `accepts()`로 코멘트 이벤트만 전달하도록 제한합니다.
- [ ] Hermes 콜백 서명 검증 (외부에서 서버 방향). (llms-todo 3번)
- 주의: github-app의 `readonly-todo.md`는 수정하지 않습니다.

## 사용자 작업

- [ ] GitHub App 설정에서 이벤트 구독 확인: Issue comment, Pull request, Pull request review, Pull request review comment, Commit comment, Push.
- [ ] GitHub App 권한 확인: contents(읽기), pull_requests, checks. 코멘트 게시를 하려면 해당 쓰기 권한도 필요합니다.
- [ ] 위 "결정 필요" 항목에 답변.
- [ ] Slack Bot 사용 시 토큰 발급 (개인 채널).
- [ ] Claude Code OAuth 로그인이 Hermes 실행 환경(같은 OS 사용자)에서 유효한지 확인.

## 보안 체크리스트

- 웹훅 수신 포트를 외부에 노출하지 않습니다. 외부 접점은 Cloudflare Worker 하나로 유지합니다.
- 모든 라우트에 HMAC secret을 설정합니다. `INSECURE_NO_AUTH`를 사용하지 않습니다.
- Claude Code 실행 시 쓰기, 네트워크, 임의 명령 실행을 허용하지 않습니다.
- diff 안의 지시문을 명령으로 해석하지 않습니다.
- secret과 토큰을 이 레포에 커밋하지 않습니다.
- 평가 결과를 게시하기 전에 앱 자신이 쓴 코멘트로 인한 무한 반복이 없는지 확인합니다 (github-app은 Bot 코멘트를 무시합니다).

## 완료

(없음)
