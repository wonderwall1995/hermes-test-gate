# llms-todo

hermes-test-gate (가제: testgate)의 작업 목록입니다.
이 파일은 LLM이 관리합니다. 기획 원문은 github-app 레포의 `readonly-todo.md`(사용자 전용, 수정 금지)입니다.
사용자가 직접 하는 일은 [user-todo.md](user-todo.md)에서 관리합니다.
영역은 `할 일`, `나중에 할 일`, `완료` 세 개입니다. 상태 표기: [ ] 미착수, [?] 결정 필요, [x] 완료.
코드 작업은 사용자가 시작을 지시한 뒤에 합니다.

## 할 일

지금 단계의 목표: 이벤트가 GitHub에서 Hermes까지 도착하고, 필터가 `/qa` 코멘트만 통과시키는 것을 증명합니다. 분석과 결과 게시는 그 다음입니다.

- [x] 구현 형태 확정 (2026-10-13): 필터는 라우트 `script`, 분석 절차는 Hermes 스킬. 분석 자체는 Claude Code가 합니다 (구독 로그인).
- [ ] 레포 기본 문서: 본 레포의 CLAUDE.md를 작성합니다 (세션 규칙, 구조).

- [ ] 보조 모델 경고 잔여 확인: `google/gemini-3.6-flash` PAID lane 경고가 1회 남아 있습니다. 기록된 호출은 모두 deepseek입니다. 경고는 폴백 클라이언트를 만들 때 한 번 찍히는 것으로 보이며, 실제 호출 여부는 OpenRouter 사용량 페이지에서 확인합니다 (사용자).


## 나중에 할 일

- [ ] 보고서 양식 작성: 마크다운. 구성은 (1) 대상(PR, 커밋), (2) 변경 요약, (3) 변경별 테스트 언급 여부 표, (4) 테스트되지 않은 항목과 이행 요청, (5) 맨 아래 세션 이름 `[PR번호-커밋ID]` 또는 `[PR번호]`. 세션 이름은 `hermes sessions rename`의 제목과 같은 값입니다.
- [ ] 세션 제목 지정: 분석 스킬의 마지막 단계에서 `hermes sessions rename "$HERMES_SESSION_ID" "PR<번호>-<커밋ID>"`를 실행합니다. 확인 필요: 터미널 도구가 `HERMES_SESSION_ID` 환경 변수를 실제로 물려받는지 (스킬 본문의 `${HERMES_SESSION_ID}` 치환은 가능함). 제목이 비어 있는 세션은 `chat_id`(delivery ID)로 찾습니다.

분석과 결과 게시 단계의 작업입니다. 위 "할 일"이 끝난 뒤에 시작합니다.

- [ ] 커밋ID 검증: 코멘트의 커밋ID가 해당 PR에 속한 커밋인지 분석 단계에서 확인합니다. 속하지 않으면 분석하지 않고 그 사실을 알립니다.
- [ ] 분석 스킬의 출력 스키마에 `mode`(결과 평가 또는 설계서 작성) 포함. 서술이 없거나 모호할 때의 규칙 정의.
- [ ] 허용 명령 제한: 에이전트가 아무 curl이나 실행하지 못하게 합니다. 고정 주소로만 보내는 작은 스크립트를 두고 에이전트는 그것만 부르게 하는 방식을 제안합니다. 구현 단계에서 구체안을 냅니다.
- [ ] QA 체크리스트 파서: 코멘트 본문에서 sha, 항목 목록 추출.
- [ ] diff 대상 해석: PR 번호, 커밋 sha, 브랜치명 중 무엇이 들어와도 대상 diff를 결정합니다.
- [ ] diff 수집 (Claude Code가 실행합니다. Hermes 본체는 diff를 계산하지 않습니다): `gh` CLI 또는 GitHub API로 커밋 diff와 PR diff 수집. 큰 diff는 파일별로 분할하고 요약 폴백을 둡니다.
- [ ] 저장소 접근: 대상 레포를 로컬에 클론하는 위치와 정리 규칙. 임시 worktree 사용을 권장합니다.
- [ ] Claude Code 헤드리스 실행기: OAuth 구독 로그인 사용, 읽기 전용 도구만 허용, 네트워크 차단.
- [ ] 평가 프롬프트와 JSON 출력 스키마: 판정, 점수, 누락 항목.
- [ ] 프롬프트 인젝션 방어: diff와 체크리스트를 비신뢰 입력으로 취급합니다. 출력 스키마를 검증합니다.
- [ ] 테스트 설계서 요청 처리: 요청 문법, 입력(diff), 출력 형식 정의.
- [ ] 분석 입력 추상화: 트리거 출처(GitHub 코멘트, 이후 Slack)와 결과 출력처를 분리합니다.
- [ ] 결과 게시: 세션 마지막에 curl로 github-app에 서명된 POST를 보냅니다. 게시 전 결과 형식을 검증합니다.
- [ ] github-app: 코멘트 게시용 인바운드 엔드포인트를 추가합니다 (installation token으로 PR 코멘트 작성). HMAC 서명 검증 필수, `deliveryId`로 중복 방지.
- [ ] github-app: 범용성을 유지합니다. 필터링 로직을 넣지 않습니다. 허용 목록(`ALLOWED_REPOS`, `ALLOWED_ACTORS`)은 선택 기능으로만 둡니다.
- [ ] github-app: Hermes 콜백 서명 검증 (외부에서 서버 방향).
- [ ] 서명을 방식 B(`X-Webhook-Signature-V2` + `X-Webhook-Timestamp`)로 올립니다. A로 연결을 증명한 뒤에 진행합니다. 재전송 공격을 막기 위함입니다.
- [ ] 중복 처리: `deliveryId` 기준 멱등 처리 (github-app은 실패 시 성공한 sink에도 재전송합니다).
- [ ] 오류 처리: 실패, 재시도, 타임아웃, 로깅.
- [ ] 테스트: mock 이벤트로 end-to-end 확인.
- [ ] `hermes project create`로 본 레포 등록 (선택, 세션 그룹핑 용도).
- [ ] Slack 트리거와 Slack 게시 (Slack 봇이 생긴 뒤). 설계에서 확장을 막지 않습니다.
- 주의: github-app의 `readonly-todo.md`는 수정하지 않습니다.

## 완료

- [x] 회고와 이식성 정리 (사용자 승인, 2026-10-13):
  - `~/.hermes/` 밖의 산출물 점검: 루트 외 불필요한 코드 산출물 없음 (아래 "회고 결과" 표).
  - 필터의 허용 계정을 코드에서 제거. `$HERMES_HOME/testgate.json`에서 읽고 없으면 모두 버림(종료 코드 1, 로그에 사유). 단위 테스트 26건 통과, 설치본을 환경 변수 없이 실행해도 설정을 찾음(스크립트 위치 기준).
  - `scripts/install.sh` 추가(`--check` 포함, pnpm 불필요, `HERMES_HOME` 기본 `~/.hermes`). mock 도구는 `HERMES_HOME` 사용, 서명은 openssl 대신 python, 작성자는 `testgate.json`에서 읽음.
  - `package.json`: `~/.hermes` 하드코딩 제거, `gateway:status`는 curl만 사용, 재시작은 `gateway:restart:systemd`와 `gateway:restart:docker`로 분리.
  - `docs/setup.md` 추가(호스트와 Docker 안내), `docs/mock-test.md`에서 개인 경로와 계정 제거, `.gitignore`에 `testgate.json` 추가.
  - 작업 메모 두 파일에서 개인 정보(계정, 사용자 이름, 이메일 앞부분)를 일반 표현으로 교체 (사용자 결정: 개인 정보만 지우고 올림).
  - `~/.hermes/testgate.json` 생성 (사용자 설정, 프로젝트 밖).
- [x] 필터를 확정 문법에 맞게 수정 (2026-10-13): `scripts/qa_filter.py`가 `qa: {commit, text, truncated}`를 출력합니다 (이전 `qa.command` 제거, 라우트 프롬프트는 이 값을 쓰지 않아 영향 없음). 단위 테스트 22건 통과(`pnpm filter:test`), 사용자 예시 3개 포함. 설치본 갱신(`pnpm filter:install`), mock 비에이전트 5케이스 재확인. 라우트 프롬프트는 아직 연결 증명용이며 서술 본문을 에이전트에 넘기지 않습니다.
- [x] mock 도구 확장: 케이스 `qa-commit`, `qa-multiline`, `qa-design`, `qa-empty` 추가, JSON을 python으로 생성(줄바꿈과 따옴표 안전), `MOCK_DRY_RUN=1`(`pnpm mock:dry`)은 요청을 보내지 않고 필터 결과만 출력합니다.
- [x] 세션 제목 자동 생성 끔 (사용자 결정 A, 2026-10-13 12:07): `auxiliary.title_generation.enabled: false`. 백업 `config.yaml.bak.pre-title-off.20261013`. 검증: 새 세션의 `session_model_usage`에 제목 생성 행이 없고 호출은 본 호출 1건뿐(약 $0.0002), 제목은 비어 있음(`NULL`). 이 설정은 즉시 제목과 LLM 제목을 모두 끕니다. 제목은 분석 스킬의 마지막 단계에서 지정합니다 (나중에 할 일 참조).
- [x] 보조 모델을 지정 모델로 고정 (사용자 결정, 2026-10-13 12:03): `config.yaml`에 `auxiliary:` 18개 작업(vision, web_extract, compression, skills_hub, approval, mcp, title_generation, memory_query_rewrite, tts_audio_tags, triage_specifier, kanban_decomposer, profile_describer, goal_judge, curator, monitor, background_review, moa_reference, moa_aggregator) 모두 `provider: main`, `model: deepseek/deepseek-v4-flash-0731`. 백업 `config.yaml.bak.pre-auxiliary.20261013`. 게이트웨이 재시작 후 `mock:qa`로 검증: 세션 응답 정상(`RECEIVED`), 로그 `Auxiliary title_generation: using main (deepseek/...)`, Nous 인증 경고 사라짐. `session_model_usage`에 기록된 호출은 모두 deepseek.
  - 한계: vision 작업은 deepseek이 이미지 모델이 아니라서 사용할 수 없습니다 (이전에도 `check_vision_requirements`가 False였음).
  - 한계: `PAID lane` 경고는 deepseek 자체에도 찍힙니다 (무료 SKU가 아니라는 일반 경고).
  - 관찰: 제목 생성 호출이 입력 356, 출력 1348 토큰(추론 1313)으로 약 $0.00087이었습니다. 세션 본 호출(약 $0.00014)의 6배입니다.
- [x] 연결 증명 완료 (2026-10-13 11:58, 사용자 실행): 실제 GitHub PR(<GitHub 계정>/github-app #3)의 코멘트가 Worker, github-app, Hermes까지 도착함. 일반 코멘트 `test`는 `script ignored`, `/qa test`는 세션 `20261013_115806_2aff414a` 생성(delivery `e6945d70-...`). github-app 로그에 `sink 전송 완료`. 세션 추정 비용 약 $0.00024, `archived=0`.
  - 관찰: 프롬프트가 "정확히 한 단어 RECEIVED만 답하라"였지만 응답은 173자였습니다(`RECEIVED` 뒤에 프롬프트 문장을 되풀이함). 모델이 출력 형식 지시를 지키지 않을 수 있다는 뜻입니다. 결과 게시 단계에서는 지시에 의존하지 않고 출력 스키마를 코드로 검증해야 합니다.
- [x] mock `qa` 케이스 성공 (사용자 실행, 2026-10-13 11:28): HTTP 202, 세션 `20261013_112853_1858c84a` 생성, 응답 `RECEIVED`, 소요 3.9초, API 호출 1회, 입력 토큰 5537, 출력 토큰 31.
- [x] 세션 보존 확인: 분석 후 `end_reason=webhook_complete`, `archived=0`. 즉시 아카이브되지 않습니다. 장기 자동 정리 규칙은 확인하지 못했습니다.
- [x] github-app `.env`에 `HTTP_SINK_URL`, `HTTP_SINK_SECRET` 설정과 재시작 (사용자, `.env` 백업함). github-app 로그에서 `http` sink 활성화 확인.
- [x] 본 레포를 pnpm 프로젝트로 초기화 (사용자 요청, 2026-10-13): `package.json`, `.gitignore`. 반복 명령은 pnpm 스크립트로 통일(`mock:*`, `filter:*`, `gateway:*`). 앞으로 추가하는 명령도 pnpm 스크립트로 둡니다.
- [x] 사용자가 github-app `.env`에 `HTTP_SINK_URL`과 `HTTP_SINK_SECRET`을 넣고 재시작함 (사용자 보고). `.env`는 백업했다고 함.
- [x] Hermes webhook 활성화 (2026-10-13): `config.yaml`의 `platforms.webhook`에 `enabled: true`, `host: 127.0.0.1`, `port: 8644` 추가. 백업 `config.yaml.bak.pre-webhook.20261013`.
- [x] 필터 스크립트 작성과 로컬 검증: `scripts/qa_filter.py` (원본), `~/.hermes/scripts/testgate_qa_filter.py` (복사본). 심볼릭 링크는 Hermes가 `~/.hermes/scripts/` 밖으로 해석되는 경로를 거부해서 복사본을 씁니다. 원본을 고치면 `pnpm filter:install`로 복사본을 갱신합니다 (`pnpm filter:check`로 동기 확인). 통과 1건, 버림 6건 확인.
- [x] 라우트 `github-app` 생성: 이벤트 `comment`, 스크립트 필터, deliver `log`, 연결 증명용 프롬프트(본문 미포함, 응답 `RECEIVED`). 라우트는 `~/.hermes/webhook_subscriptions.json`에 있습니다.
- [x] secret 생성과 보관: 값은 `~/.hermes/webhook_subscriptions.json`(권한 600)과 github-app의 `.env`에만 있습니다. 중간 전달용 `webhook-github-app.secret` 파일은 사용자 요청으로 삭제했고, mock 도구는 라우트 설정에서 직접 읽습니다. 값은 출력하거나 문서에 적지 않았습니다.
- [x] 게이트웨이 재시작 (2026-10-13 11:21): webhook과 Discord 모두 connected. `127.0.0.1:8644`만 수신, `/health` 정상.
- [x] mock 도구 작성: `scripts/mock_post.sh`, `docs/mock-test.md`. 에이전트를 시작하지 않는 5개 케이스를 실행해 확인했습니다 (올바른 서명은 통과해 스크립트까지 도달, 잘못된 서명은 401, 나머지 4개는 ignored).
- [x] github-app 서비스 재시작 (사용자 실행, 2026-10-13 11:17 KST). active, healthz 정상, 빌드 시각 이후 시작 확인. 새 헤더 적용됨.
- [x] github-app `pnpm build` 실행, `dist/`에 새 헤더 반영 확인 (2026-10-13). 서비스 재시작은 sudo 때문에 미실행.
- [x] github-app 공개 대비 민감 정보 점검 (2026-10-13): 비밀 파일은 추적되지 않음. 개인 식별 정보 3건 발견, 사용자 결정 대기 (user-todo).
- [x] github-app 헤더 호환 수정 (방식 A): `x-hub-signature-256`으로 서명, `x-github-event` 헤더 추가 (값은 `event.kind`). `src/sinks/http.ts`, `test/sinks.test.ts` 수정, `pnpm test` 77건 통과, `pnpm typecheck` 통과. 커밋 안 함 (2026-10-13).
- [x] github-app 레포 분석: 구조, Sink, 헤더 불일치 2건 확인 (2026-10-12).
- [x] `~/.hermes/projects/` 폴더 생성과 hermes-test-gate 클론 (사용자 진행).
- [x] hermes-agent 저장소의 CLAUDE.md 작성.
- [x] 방향 결정 (2026-10-13, 아래 "결정 사항").
- [x] 허용 작성자 확정: `<GitHub 계정>` (사용자 제공).
- [x] `HTTP_SINK_URL`이 현재 비어 있음을 확인 (사용자 확인).

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
| diff 수집, 평가, 게시 | 본 레포 (testgate) | "나중에 할 일" |
| GitHub, Slack 설정 | 사용자 | user-todo.md |

## 결정 사항 (2026-10-13, 사용자 확정)

- 역할 원칙: github-app은 범용 수집기입니다. 필터 없이 이벤트를 전부 전달합니다. Hermes는 물류 창고 겸 분석 기구입니다. 도착한 웹훅을 버리거나 수용하는 판단은 Hermes가 합니다.
- 세션 정책: 분석 세션은 분석 요청 1건이 도착할 때만 시작합니다. 평소에는 세션이 없습니다. 분석이 끝난 세션은 보존 상태로 둡니다 (아카이브하지 않음).
- 분석 요청의 종류: (1) QA의 테스트 결과 전송, (2) 테스트 설계서 요청. 두 번째는 원래 기획에 없던 항목입니다.
- 분석 대상 diff:
  - PR이 있으면: PR에 쌓인 모든 커밋을 합친 diff.
  - PR이 없으면: 커밋 하나의 diff, 또는 브랜치에 쌓인 전체 diff.
  - 기준 브랜치: main, dev, develop, staging 등 범용 브랜치.
  - diff 생성과 분석은 Hermes가 하지 않습니다. Hermes가 Claude Code를 실행시켜 수행합니다.
- 트리거: 기본은 PR 코멘트입니다. 이후 Slack에서도 같은 요청을 받을 수 있어야 합니다. Slack 봇은 아직 없고 당장 만들 계획도 없습니다. 다만 설계에서 Slack 확장을 막지 않아야 합니다.
- 결과 반환 경로: 분석 세션 마지막에 Hermes가 terminal 도구로 `curl`을 실행해 github-app의 신규 엔드포인트에 서명된 POST를 보냅니다. github-app이 코멘트를 게시합니다.
- 구현 형태: 필터는 라우트 `script`, 분석 절차는 Hermes 스킬, 분석 본체는 Claude Code(구독 로그인)가 수행합니다. Hermes 세션의 주 모델(OpenRouter 종량제)은 오케스트레이션만 합니다.
- `/qa` 코멘트 문법 확정 (2026-10-13, 사용자): 두 가지뿐입니다.
  - `/qa [커밋ID] 자유 서술`
  - `/qa 자유 서술`
  - 커밋ID는 대괄호 안의 16진수 7~40자입니다. 대괄호가 없는 것은 전부 자유 서술로 봅니다 (예: `abc1234 확인함`은 자유 서술).
  - 자유 서술은 여러 줄이어도 됩니다. 길이 상한 10000자, 넘으면 잘라서 `truncated: true`로 표시합니다.
  - 기준 브랜치(base)는 코멘트에 쓰지 않습니다. PR 정보(PR이 합쳐질 대상 브랜치)에서 얻습니다.
  - 결과 제출과 테스트 설계서 요청을 문법으로 나누지 않습니다. 둘 다 자유 서술이고, 어느 쪽인지는 분석(Claude)이 서술을 보고 판단합니다. 판단 결과는 출력 스키마의 `mode` 값으로 받아 코드로 검증합니다.
  - `/qa`만 쓰면(서술 없음) 필터는 통과시킵니다. 서술이 없는 요청의 처리는 분석 스킬에서 정합니다 (제안: 설계서 요청으로 간주).
- 판정 기준 (사용자 결정, 2026-10-13): 합격 점수나 임계값은 없습니다.
  - 변경된 파일(또는 변경된 동작)마다 QA 서술에 그 테스트에 대한 언급이 있는지 봅니다.
  - 언급이 없는 변경은 "테스트되지 않음"으로 보고, 해당 테스트를 이행하라고 QA에게 다시 요청합니다.
  - 서술이 변경 파일명을 직접 쓰지 않을 수 있으므로(예: "로그 확인", "모킹 확인"), 서술과 변경 내용의 대응은 Claude가 의미로 판단합니다.
  - 결과는 마크다운 보고서입니다. 보고서 맨 아래에 세션 이름을 적습니다.
  - 세션 이름 형식: `[PR번호-커밋ID]`. 코멘트에 커밋ID가 있을 때만 커밋ID를 붙이고, 없으면 `[PR번호]`만 씁니다.
- 허용 작성자: 본인 계정만. 허용 목록은 Hermes 필터 스크립트에 둡니다.
- 결과 게시: 분석 내용만 GitHub 코멘트로 보냅니다. github-app의 Bot 이름으로 게시합니다. Slack 게시는 이후 과제입니다.

## 확인된 사실 (2026-10-12 코드 확인)

- Hermes 웹훅 수신: `hermes-agent/gateway/platforms/webhook.py`. 경로는 `POST /webhooks/{route_name}`입니다.
- Hermes 라우트 설정: `events`, `secret`(필수), `prompt` 템플릿, `skills`, `deliver`, `deliver_extra`, `script`. `hermes webhook subscribe`로 생성합니다.
- Hermes 서명 검증이 인식하는 헤더: `X-Hub-Signature-256`, `X-Webhook-Signature-V2`(+`X-Webhook-Timestamp`), `X-Webhook-Signature`(구형), GitLab, Linear, Svix.
- 이 PC의 현재 상태: `config.yaml`에 webhook 설정이 없고 구독 파일도 없습니다. 웹훅 수신은 꺼져 있습니다. github-app의 `HTTP_SINK_URL`도 비어 있습니다 (사용자 확인).
- Hermes는 웹훅을 버릴 수 있습니다. 라우트에 `events` 헤더 필터, `filter`(페이로드 조건), `script`(스크립트가 keep 여부를 반환)가 있습니다. 버려진 요청은 LLM 비용이 0입니다. 단, `events` 필터는 `X-GitHub-Event` 헤더가 필요합니다.
- Hermes 웹훅 세션은 요청 1건당 1개입니다 (`chat_id = webhook:{route}:{delivery_id}`). "분석 요청 1건 = 세션 1개" 정책과 구조가 일치합니다. 별도로 `api_server`(`POST /v1/runs`, `X-Hermes-Session-Key`)도 있으나 현재 설정은 꺼져 있습니다.
- Hermes 내장 `deliver` 대상은 telegram, discord, slack, github_comment(gh CLI) 등입니다. 임의의 HTTP 콜백 대상(github-app)은 없습니다.
- github-app은 현재 코멘트 게시 기능이 없습니다. `src/github/auth.ts`가 installation token을 발급할 뿐이고, 외부에서 들어오는 엔드포인트는 `/healthz`와 webhook 수신뿐입니다.
- 이 PC의 `config.yaml`은 `session_reset.mode: none`입니다. 웹훅 세션의 자동 아카이브 여부는 아직 확인하지 않았습니다.
- Hermes `project` 기능(`hermes project create`)은 `projects.db`에 폴더를 등록할 뿐입니다. 웹훅 라우트와 연결되지 않습니다. `~/.hermes/projects/` 폴더도 Hermes가 자동 인식하지 않습니다.
- Hermes에는 `skills/github/` 아래에 `github-code-review`, `github-pr-workflow`, `github-issue-to-pr`가 이미 있습니다. 재사용 여부를 먼저 검토합니다.

## 연동 차단 요인 (github-app 쪽 수정 필요)

github-app의 `src/sinks/http.ts`가 보내는 요청을 Hermes가 현재 거부합니다.

1. 서명 헤더 불일치: github-app은 `X-Signature-256`을 보냅니다. Hermes는 이 이름을 인식하지 않아 401을 반환합니다.
   - 선택지 A: 헤더를 `X-Hub-Signature-256`으로 변경합니다 (값 형식 `sha256=<hex>`는 이미 같습니다).
   - 선택지 B: `X-Webhook-Signature-V2`와 `X-Webhook-Timestamp`를 사용합니다. 재전송 공격을 막을 수 있습니다.
2. 이벤트 종류 불일치: github-app 본문은 `{deliveryId, event:{kind,...}}`이고 `X-GitHub-Event` 헤더가 없습니다. Hermes는 이벤트를 항상 `unknown`으로 분류합니다. 라우트에 `events` 필터를 걸면 모든 요청이 무시됩니다.
   - 선택지: `X-GitHub-Event` 헤더를 추가합니다. 값은 `event.kind`에서 만듭니다. 또는 본문 최상위에 `type`을 추가합니다.

결정 (2026-10-13): 선택지 A로 먼저 연결을 증명하고, 이후 B로 옮깁니다. A는 적용 완료(코드), 서비스 재시작 전입니다.
주의: `X-GitHub-Event` 값은 GitHub 이벤트 이름이 아니라 앱 내부 종류입니다 (예: GitHub의 `issue_comment`가 아니라 `comment`). Hermes 라우트의 `events` 필터에는 이 값을 씁니다.

## 회고 결과 (커밋 전 점검, 2026-10-13)

`~/.hermes/`(프로젝트 밖)에 생긴 것:

| 항목 | 종류 | 판단 |
| --- | --- | --- |
| `config.yaml` (webhook, auxiliary 18개, 제목 끔) | 사용자 설정 | 필요. 프로젝트 밖 설정이 맞음. 프로젝트에는 포함하지 않음 |
| `config.yaml.bak.pre-webhook/pre-auxiliary/pre-title-off.20261013` | 백업 3개 | 설정이 안정되면 지워도 됨 |
| `webhook_subscriptions.json` | Hermes CLI가 만든 라우트 + secret | 필요. 프로젝트에 넣지 않음 |
| `scripts/` 폴더, `scripts/testgate_qa_filter.py` | 필터 설치본 | 필요. Hermes가 이 위치만 허용함. 원본은 본 레포 `scripts/qa_filter.py` |
| `state.db`의 webhook 세션 4건 | 테스트 세션 (mock 3, 실제 1) | 지워도 됨. 비용 합계 약 $0.0007 |
| (삭제됨) `webhook-github-app.secret` | 임시 파일 | 이미 삭제 |

그 밖에 `~/.hermes/` 루트나 다른 위치에 만든 코드 산출물은 없습니다.

프로젝트 안의 이식성 문제 (Docker Hermes에서는 `HERMES_HOME=/opt/data`, 호스트 `~/.hermes`를 마운트, systemd 없음, 이미지에 python3와 curl은 있고 pnpm, openssl 확인 안 됨, Claude Code CLI는 이미지에 없음):

- `package.json`: `~/.hermes` 하드코딩 3곳, `systemctl --user` 2곳 (Docker에는 systemd 없음).
- `scripts/mock_post.sh`: 기본 경로 `$HOME/.hermes`, 작성자와 레포 소유자 하드코딩, 서명에 `openssl` 사용.
- `scripts/qa_filter.py`, `scripts/test_qa_filter.py`: 개인 GitHub 계정이 상수로 들어 있음.
- `docs/mock-test.md`: 호스트 전용 명령과 경로.
- `llms-todo.md`, `user-todo.md`: 개인 계정, 홈 경로, 이메일 앞부분이 들어 있음. 저장소를 공개한다면 정리 또는 제외가 필요함.
- 핵심 산출물(필터, 이후 스킬과 래퍼)이 pnpm에 의존하면 안 됨. 이미지에는 npm만 있고 pnpm이 없음. pnpm은 호스트 편의 래퍼로만 둠.

제안: `HERMES_HOME` 환경 변수를 기본으로 쓰고(기본값 `~/.hermes`), 허용 계정은 `$HERMES_HOME/testgate.json`(프로젝트 밖, 사용자 관리)에서 읽고 없으면 모두 버림(fail closed), 서명은 python으로, 설치는 `scripts/install.sh`(pnpm 불필요), 작업 메모 두 파일은 개인 정보를 빼거나 `.gitignore`로 제외.

## 설계 메모

### 감지 경로 (`/qa` 코멘트를 누가 감지하는가)

GitHub은 코멘트 내용을 해석하지 않습니다. 구독한 이벤트를 전부 보낼 뿐입니다. 감지는 Hermes의 라우트 `script`가 합니다.

1. 사용자가 PR에 코멘트를 씁니다 (GitHub App이 Issue comment 이벤트를 구독해야 합니다. PR 본문 스레드의 코멘트도 이 이벤트입니다).
2. GitHub이 Worker로 웹훅을 보냅니다. github-app이 20초 간격으로 가져옵니다.
3. github-app은 코멘트를 정규화하고 Sink로 전부 전달합니다 (본문, 작성자, 레포, PR 번호 포함).
4. Hermes 라우트의 `script`가 stdin으로 페이로드 JSON을 받습니다. 본문이 `/qa`로 시작하고 작성자가 허용 목록에 있으면 JSON을 stdout으로 출력합니다. 그렇지 않으면 빈 출력 또는 `[SILENT]` 또는 0이 아닌 종료 코드로 버립니다. 버려지면 세션이 만들어지지 않습니다.
5. 통과한 요청만 분석 세션이 됩니다 (`webhook:{route}:{delivery_id}`).

지연: pull 간격 20초 때문에 코멘트 후 분석 시작까지 최대 약 20초가 걸립니다.
필터 스크립트 위치: `~/.hermes/scripts/` 아래만 허용됩니다. 스크립트는 `~/.hermes/`가 아닌 본 레포에서 관리하고 연결(심볼릭 링크 또는 복사)하는 방안을 검토합니다.

실제 동작 검증이 필요한 항목:
- [ ] github-app 헤더 호환 수정 후 Hermes가 요청을 수락하는지 (현재는 401).
- [ ] 페이로드가 `script`에 전달되는 형태에서 코멘트 본문과 작성자를 읽을 수 있는지. 전달 형태는 `{deliveryId, event:{kind:"comment",...}}`입니다.
- [ ] 필터 스크립트가 일반 코멘트를 버리는지, `/qa` 코멘트만 통과시키는지 (mock POST로 확인).
- [ ] Bot이 쓴 결과 코멘트가 다시 분석을 일으키지 않는지 (github-app이 Bot 이벤트를 전달하지 않습니다).

### 결과 반환 경로

github-app이 Bot 이름으로 코멘트를 게시하려면 Hermes에서 github-app으로 결과가 가야 합니다. 현재 양쪽 모두 이 경로가 없습니다.

- 확정: 분석 세션의 마지막 단계에서 Hermes가 terminal 도구로 `curl`을 실행해 github-app의 신규 엔드포인트에 결과를 POST합니다. 서명(HMAC)을 붙입니다. 기획의 "curl 따위의 명령어"와 일치합니다. Hermes 코어 수정이 없습니다.
- 보류된 대안: Hermes 플러그인으로 새 `deliver` 대상(HTTP 콜백)을 만드는 방식.
- 주의: 에이전트가 명령을 실행하므로, 허용할 명령(대상 URL 하나의 curl)을 제한하는 방법을 정해야 합니다.
- 공통 필요 사항: github-app에 인바운드 엔드포인트와 서명 검증을 추가합니다. 중복 게시 방지를 위해 `deliveryId`를 포함합니다.

## 보안 체크리스트

- 웹훅 수신 포트를 외부에 노출하지 않습니다. 외부 접점은 Cloudflare Worker 하나로 유지합니다.
- 모든 라우트에 HMAC secret을 설정합니다. `INSECURE_NO_AUTH`를 사용하지 않습니다.
- Claude Code 실행 시 쓰기, 네트워크, 임의 명령 실행을 허용하지 않습니다.
- diff 안의 지시문을 명령으로 해석하지 않습니다.
- secret과 토큰을 이 레포에 커밋하지 않습니다.
- 평가 결과를 게시하기 전에 앱 자신이 쓴 코멘트로 인한 무한 반복이 없는지 확인합니다 (github-app은 Bot 코멘트를 무시합니다).
