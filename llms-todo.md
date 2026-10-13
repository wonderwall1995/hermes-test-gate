# llms-todo

hermes-test-gate (가제: testgate)의 작업 목록입니다.
이 파일은 LLM이 관리합니다. 기획 원문은 github-app 레포의 `readonly-todo.md`(사용자 전용, 수정 금지)입니다.
사용자가 직접 하는 일은 [user-todo.md](user-todo.md)에서 관리합니다.
영역은 `할 일`, `나중에 할 일`, `완료` 세 개입니다. 상태 표기: [ ] 미착수, [?] 결정 필요, [x] 완료.
코드 작업은 사용자가 시작을 지시한 뒤에 합니다.
마지막 정리: 2026-10-13 (완료 항목을 주제별로 묶고, 폐기된 결정과 해결된 차단 요인을 현재 사실로 고침).

## 할 일

현재 `main`(`427e97e`)에 기능이 모두 들어가 동작합니다. 남은 것은 실제 코멘트 확인과 정리입니다.

- [ ] (사용자) 수정 후 실제 PR 코멘트 시험: 필터가 래퍼를 직접 시작하는 방식으로 바꾼 뒤(13:55)에는 실제 GitHub 코멘트가 아직 한 건도 처리되지 않았고 mock 시험만 통과했습니다. 상세는 user-todo.md.
- [ ] 놓친 요청 복구 여부 결정(사용자 승인 필요): 수정 전 13:46에 세션 LLM이 거부해서 분석되지 않은 요청이 보고서 없이 남아 있습니다 (PR #3의 `/qa` 코멘트, delivery `02cb4620-c6c1-11f1-9489-5b323d95b9cc`). 같은 ID로 래퍼를 다시 실행하면 복구되지만 PR에 Bot 코멘트가 실제로 게시됩니다. 요청 파일은 30일 뒤 삭제됩니다.
- [ ] `.pyc` 추적 해제(사용자 승인 필요): `scripts/__pycache__/qa_filter.cpython-314.pyc`가 커밋에 들어 있어 매 변경마다 이진 파일 변경이 끼고 병합 충돌에도 섞였습니다. `git rm --cached` 커밋 하나로 해결하며 푸시는 사용자 몫입니다.
- [ ] (선택) 이 레포의 `CLAUDE.md` 작성: 세션 규칙, 구조.
- [ ] (사용자 확인) 보조 모델 경고: 로그에 `google/gemini-3.6-flash` PAID lane 경고가 1회 남아 있습니다. 기록된 호출은 모두 deepseek이며 경고는 폴백 클라이언트를 만들 때 한 번 찍히는 것으로 보입니다. 실제 호출 여부는 OpenRouter 사용량 페이지에서만 확인할 수 있습니다.

## 나중에 할 일

- [ ] 실제 PR 추가 시험(Bot 코멘트가 달림, 사용자 작성): (1) 같은 PR에 `/qa` 코멘트 두 번으로 순번 `#1`, `#2`와 이어받기 확인, (2) `/qa [sha] ...`(PR에 속한 커밋), (3) PR에 없는 커밋ID(github-app 404 -> 일반 실패 코멘트), (4) 서술 없는 `/qa`. `/qa free:`는 PR #3에서 실제로 확인했습니다(아래 완료).
- [ ] (선택) 감시자: 요청 파일은 있는데 보고서도 실패 코멘트도 없는 건을 주기적으로 찾아 래퍼를 다시 실행합니다. 근거: 분석 중 게이트웨이를 재시작하면 래퍼가 함께 끊기고, 실제로 보고서 없이 남은 요청이 1건 있습니다(위 놓친 요청).
- [ ] 비용 관리: 파일이 많은 PR은 호출당 목록가가 약 $0.3 수준입니다(30개 파일 설계서 $0.30, 6개 파일 평가 $0.04). `analysis.max_diff_chars`(현재 12만 자), 추론 강도, 설계서 시나리오 수 제한 중 필요한 것을 정합니다.
- [ ] 문서만 바뀐 변경(README 등)의 처리 규칙: 지금은 모델이 "동작 테스트 불필요, 내용 일치만 확인"처럼 부드럽게 요청합니다.
- [ ] 도메인 지식 문서 연결: `diagnosis.json` 같은 문서의 형식과 "어떤 PR에 어떤 문서가 해당하는가"를 정합니다. 현재는 `analysis.knowledge_dirs`의 모든 `.json`/`.md`를 상한 안에서 읽습니다 (사용자에게 예시를 받아야 함).
- [ ] Docker: 이미지에 Claude Code CLI가 보이지 않습니다. CLI 설치, 구독 로그인 유지, 필터가 래퍼를 백그라운드로 띄우는 동작(컨테이너의 프로세스 정리 방식) 확인이 필요합니다. 호스트에서만 시험했습니다.
- [ ] 서명 방식 B: github-app -> Hermes 구간을 `X-Webhook-Signature-V2` + `X-Webhook-Timestamp`로 올려 재전송 공격을 막습니다. 지금은 `X-Hub-Signature-256`(방식 A)입니다. 반대 방향(Hermes -> github-app)은 이미 타임스탬프 방식입니다.
- [ ] Slack 트리거와 게시 (Slack 봇이 생긴 뒤). 설계에서 확장을 막지 않았습니다(트리거 출처와 출력처가 분리됨).
- [ ] (선택) `hermes project create`로 이 레포 등록: 세션 그룹핑 용도이며 웹훅과 연결되지 않습니다.
- [ ] (선택) 정리: `state.db`의 mock 시험 세션 5건, `config.yaml.bak.pre-*` 4개. 설정이 안정되면 지워도 됩니다.

## 완료

### 연결과 기반 (2026-10-12 ~ 13)
- [x] github-app 분석과 헤더 호환 수정(방식 A): github-app의 sink가 `X-Signature-256`을 보내 Hermes가 401로 거부했고 `X-GitHub-Event`도 없었음. `x-hub-signature-256` 서명과 `x-github-event`(값은 GitHub 이벤트 이름이 아니라 앱 내부 종류 `event.kind`, 예: `comment`)로 수정.
- [x] Hermes 웹훅 활성화: `config.yaml`의 `platforms.webhook`(`127.0.0.1:8644`), 라우트 `github-app`(이벤트 `comment`, 스크립트 필터). 서명 키는 `webhook_subscriptions.json`(권한 600)과 github-app의 `.env`에만 있음. `/health` 정상.
- [x] 연결 증명(11:58): 실제 GitHub PR 코멘트가 Worker, github-app, Hermes까지 도착. 일반 코멘트는 무시, `/qa`는 세션 생성.
- [x] github-app 쪽 조회·게시 API 구현(사용자 승인): `POST /api/pr`, `POST /api/comment`. 서명은 `x-hermes-timestamp` + `x-hermes-signature`(재전송 창 300초), 키는 github-app의 `HERMES_API_SECRET`. 자세한 내용은 github-app의 llms-todo.md Done 25번.
- [x] 사용자 설정 확인: GitHub App의 Issue comment 구독, Pull requests와 Issues 쓰기 권한, 대상 레포 접근.

### 분석기
- [x] `testgate/` 패키지(표준 라이브러리만, 설계는 `docs/design-analysis.md`): diff 소스(로컬 git, github-app), 지식 소스(폴더), 난수 구분자 프롬프트, 출력 스키마와 코드 후처리, `claude -p` 실행기, 마크다운 보고서(맨 아래 `세션: [...]`), CLI(`pnpm analyze`).
- [x] Claude 실행 방식: 도구 없음(`--tools ""`), MCP와 슬래시 명령과 사용자 설정과 세션 저장 모두 끔, 빈 임시 폴더, 구독 로그인(`--bare`는 OAuth를 읽지 않아 쓰지 않음). 모델 `claude-sonnet-5-5`, 추론 강도 `medium`(사용자 결정, `testgate.json`의 `analysis`). 기본 모델(Opus)은 사소한 호출도 목록가 $0.03.
- [x] 코드가 덮어쓰는 규칙: 서술이 비면 설계서 모드, 변경 파일 목록과 결과를 일치시킴(빠진 파일은 확인 불가, 모르는 경로는 제외), 근거 인용이 서술에 없으면 확인 불가로 낮춤, 잘린 diff는 확인 불가, 판정은 코드가 계산.
- [x] 실제 Claude 시험: 평가 모드(구현 누락까지 지적), 설계서 모드, 커밋 단위, 인젝션 시험 2회(서술 속 지시문을 따르지 않고 비고에 남김, `@` 멘션 무력화).
- [x] 보안 보강: 모델이 쓴 문장의 마크다운 이미지와 링크 문법을 무력화(이미지는 GitHub이 대신 불러 PR 내용이 주소에 실려 나갈 수 있음). 코드 블록 안의 `<`는 유지.

### 코멘트 문법, 연속성, 세션 이름 (사용자 결정)
- [x] 문법: `/qa [커밋ID] 서술`, `/qa 서술`, `/qa free: [커밋ID] 서술`. 커밋ID는 대괄호 안 16진수 7~40자(없으면 전부 서술), `free:`는 소문자와 콜론 정확히. base 브랜치는 PR 정보에서 얻음. `free:`는 판정 표 없이 답변만, diff 본문은 커밋ID가 있을 때만, 빈 질문은 Claude 호출 없이 안내만.
- [x] PR 대화 기록(`$HERMES_HOME/testgate/threads/<소유자>__<레포>__<PR번호>.json`, 권한 600, 파일 잠금): 요청 순번, 결과와 파일별 판정과 diff 지문, 제목 변경 이력. 개인과 조직 소유자 모두 지원.
- [x] 확인됨 이어받기: 이전 판정이 `yes`이고 diff 지문(범위 포함)이 같을 때만 이어받음. 판정은 코드가 하고 이어받은 파일은 Claude에게 보내지 않음(평가할 파일이 없으면 Claude 호출 비용 0). 바뀐 파일은 보고서 비고로 알림. 판정 기준(사용자): 합격 점수 없음, 파일마다 서술에 테스트 언급이 있는지 보고 없으면 이행 요청.
- [x] 세션 이름 `[PR번호 - PR이름 - 커밋ID #순번]`: PR이름은 40자로 줄이고 대괄호, 백틱, 줄바꿈 제거. 커밋ID는 코멘트에 있을 때만. PR 이름이 바뀌어도 이전 세션 이름은 바꾸지 않음(PR 번호가 고정 식별자).
- [x] 실제 시험: PR #2에서 설계서 모드(Bot 코멘트 약 64초 뒤 게시, 변경 파일 30개, 분석 42.7초, 목록가 약 $0.30), PR #3에서 `/qa free:` 2건(두 번째 답변이 "history 블록의 이전 요청 요약을 읽고 안다"고 정확히 답해 연속성 확인)과 설계서 1건. Bot 코멘트 이벤트는 github-app이 수집만 하고 sink로 보내지 않아 재분석 루프 없음.

### 실행 방식 변경: 세션 LLM에서 필터로 (사용자 결정 A)
- [x] 원인: 한때 Hermes 세션의 LLM이 래퍼를 실행했는데, `SOUL.md`의 보안 서약("I protect the human", "Is urgency being manufactured...") 때문에 가끔 "I'm not going to run that command"라며 거부함(실제 GitHub 요청 6건 중 1건). 거부되면 래퍼가 실행되지 않아 실패 코멘트도 없이 조용히 사라짐.
- [x] 변경: 필터가 통과 판정 후 요청을 `$HERMES_HOME/testgate/requests/<deliveryId>.json`(권한 600)에 저장하고 래퍼 `testgate-run <deliveryId>`를 백그라운드로 시작(표준 입출력을 닫고 새 세션으로). 래퍼가 없으면 저장하지 않고 종료 코드 1(fail closed), 이미 저장된 요청이면 다시 시작하지 않음. 필터 출력에는 서술 본문을 빼고 길이만 남김. 라우트 프롬프트는 "OK라고만 답하라"이고 `toolsets: terminal`은 제거(세션 LLM에게 도구가 없음). 세션은 요청의 기록으로 남음.
- [x] 래퍼: 요청 재검증(허용 소유자, 형식) -> github-app에서 PR 맥락 조회 -> 분석 -> 보고서 저장(권한 600) -> github-app으로 코멘트 게시 -> 세션 이름 변경. 실패하면 일반 문구의 실패 코멘트(`<deliveryId>-failed`로 중복 방지). 세션 이름 변경은 환경 변수 `HERMES_SESSION_ID`를 믿지 않고(게이트웨이가 프로세스 전체에 마지막 세션 값을 덮어씀) 상태 DB에서 `chat_id`로 찾으며, 세션 행이 생길 때까지 최대 20초 기다림. 표준 출력은 보고서 경로를 뺀 고정 형식 한 줄(경로를 쓰면 Hermes가 파일 첨부로 오해해 전송을 시도함).
- [x] 시험(mock, PR #2, 코멘트 게시 끔): 필터 응답 0.6초, 세션 LLM은 "OK"만 답함(도구 호출 0, 1.6초, 약 $0.00014), 래퍼는 별도로 25.7초 분석 후 보고서와 기록 저장. 서명 키가 `terminal.env_passthrough`로 필터 하위 프로세스(래퍼)까지 전달됨을 확인.
- [x] 남은 위험(위 감시자 항목): 분석 중 게이트웨이를 재시작하면 그 건의 래퍼가 함께 끊김.

### 운영 설정 (사용자 결정)
- [x] 보조 모델을 지정 모델로 고정: `config.yaml`의 `auxiliary:` 18개 작업 모두 `provider: main`, `model: deepseek/deepseek-v4-flash-0731`. 사용량 기록의 호출은 모두 deepseek. 한계: vision 작업은 이미지 모델이 아니라 사용 불가(이전에도 꺼져 있었음).
- [x] 세션 제목 자동 생성 끔(`auxiliary.title_generation.enabled: false`): 제목 생성이 세션 본 호출보다 비용이 컸음(약 $0.00087 대 $0.00014). 제목은 래퍼가 붙임.
- [x] 서명 키 전달: 값은 Hermes의 `~/.hermes/.env`(사용자 추가)의 `TESTGATE_GITHUB_APP_SECRET`, 이름은 `config.yaml`의 `terminal.env_passthrough`에 등록. 프로젝트는 비밀을 저장하거나 읽지 않고 저장소에는 이름만 있는 `.env.example`을 둠. 한때 만든 `testgate.env`와 `secrets.py`는 철회하고 삭제.
- [x] 세션 보존: 분석 후 `end_reason=webhook_complete`, `archived=0`. 장기 자동 정리 규칙은 확인하지 못함.

### 이식성과 정리
- [x] 경로는 `HERMES_HOME`(기본 `~/.hermes`, Docker 이미지는 `/opt/data`)을 따름. 허용 계정은 코드가 아니라 `$HERMES_HOME/testgate.json`(없으면 모두 버림). 서명은 python 사용. 설치는 `scripts/install.sh`(pnpm 불필요, `--check`), 라우트는 `scripts/subscribe.sh`(기존 서명 키 유지). pnpm 스크립트는 호스트 편의용(`mock:*`, `filter:*`, `gateway:*`, `route:subscribe`, `test`, `analyze`).
- [x] `$HERMES_HOME`을 여러 프로젝트가 같이 쓰므로, 이 저장소가 설치하는 파일 15개의 맨 아래에 `[hermes-test-gate] 현재 Repo(hermes-test-gate)로 생성한 파일입니다.` 표시를 붙임(`install.sh`가 설치할 때마다 붙임). `testgate.json`은 JSON이라 마지막 키 `_generated_by`, 백업 4개는 YAML 주석. 수정한 `config.yaml`, `.env`와 Hermes가 관리하는 `webhook_subscriptions.json`에는 붙이지 않음.
- [x] 작업 메모의 개인 정보를 일반 표현으로 교체(사용자 결정). github-app의 workers.dev 주소도 `<서브도메인>`으로 교체.
- [x] 스쿼시 병합으로 같은 내용이 다른 해시가 되어 생긴 충돌을 두 번 해결: `git rebase --onto origin/main <앞 PR의 원본 마지막 커밋> <브랜치>` 후 `--force-with-lease` 푸시(푸시는 사용자). 백업 브랜치 `backup/qa-free-talk-before-rebase`, `backup/claude-timeout-before-rebase`. 앞 PR이 병합된 뒤에는 새 브랜치를 병합된 `main`에서 만든다.
- [x] 테스트: 분석기 109건, 필터 32건 통과(github-app은 108건).

## 목표

QA가 PR에 테스트 서술을 자연어로 쓰면, Hermes 하위의 Claude Code가 PR의 diff를 읽고 변경된 파일마다 테스트 언급이 있는지 평가하거나(`/qa`), 테스트 설계서를 만들거나(`/qa`로 요청), 자유롭게 대화(`/qa free:`)합니다. 결과는 github-app의 Bot 이름으로 PR 코멘트로 돌려줍니다. Slack은 이후 과제입니다.

## 전체 흐름

```
GitHub
  -> Cloudflare Worker (서명 검증, 중복 제거, D1 보관)
  <- 노트북의 github-app (20초 간격 pull, ack 후 삭제)
  -> SinkRouter -> HttpSink (HTTP_SINK_URL)
  -> Hermes 웹훅 수신기 (127.0.0.1:8644/webhooks/github-app)
       라우트 필터 testgate_qa_filter.py: /qa 코멘트만 통과, 요청을 파일로 저장, 래퍼를 백그라운드로 시작
       Hermes 세션: 요청의 기록 (LLM은 OK만 답함, 도구 없음)
  -> 래퍼 testgate-run <deliveryId> (별도 프로세스)
       github-app /api/pr 로 PR 맥락 조회 -> Claude Code 분석(도구 없음) -> 보고서
       github-app /api/comment 로 Bot 코멘트 게시 -> 세션 이름 변경
```

## 역할 분담

| 구분 | 담당 | 범위 |
| --- | --- | --- |
| 이벤트 수집, 전달, GitHub API 대행 | github-app 레포 | Worker, 정규화, Sink, `/api/pr`, `/api/comment` |
| 웹훅 수신과 라우팅 | Hermes 설정 | `config.yaml`, 라우트. Hermes 코어는 수정하지 않음 |
| 필터, 래퍼, 분석, 보고서, 기록 | 본 레포 (testgate) | `scripts/`, `testgate/` |
| GitHub, Slack, 비밀 값 설정 | 사용자 | user-todo.md |

## 결정 사항 (현재 유효)

- 역할 원칙: github-app은 범용 수집기라 필터 없이 이벤트를 전부 전달합니다. 도착한 웹훅을 버릴지 판단하는 일은 Hermes가 합니다. 허용 목록은 선택 기능으로만 둡니다.
- 트리거: 기본은 PR 코멘트이고, 이후 Slack에서도 같은 요청을 받을 수 있어야 합니다(설계에서 확장을 막지 않음).
- 허용 작성자와 레포 소유자는 `$HERMES_HOME/testgate.json`의 목록입니다.
- 분석 대상 diff: PR이 있으면 PR의 모든 커밋을 합친 diff(기준 브랜치는 PR 정보에서), 커밋ID가 있으면 그 커밋 하나. 커밋ID가 그 PR에 속하는지는 github-app이 확인합니다. 분석은 Claude Code가 하고 Hermes 본체는 diff를 계산하지 않습니다.
- 판정: 합격 점수 없음. 파일마다 서술에 테스트 언급이 있는지 보고, 없으면 이행을 다시 요청. 서술과 변경의 대응은 Claude가 의미로 판단하고, 판정은 코드가 계산합니다.
- 결과: 마크다운 보고서, 맨 아래에 세션 이름. GitHub 코멘트는 github-app의 Bot 이름으로 게시합니다.
- 세션 정책: 요청이 있을 때만 세션이 생기고, 끝난 세션은 보존합니다(아카이브하지 않음).
- 분석 실행 주체는 필터가 시작한 래퍼입니다. Hermes 세션의 LLM은 분석에 관여하지 않습니다.
- 비밀은 프로젝트 밖(Hermes 환경)에 둡니다.

### 폐기된 이전 결정 (이력)

| 이전 결정 | 지금 | 이유 |
| --- | --- | --- |
| 세션 마지막에 Hermes가 terminal 도구로 `curl`을 실행해 결과를 돌려줌 | 래퍼가 github-app `/api/comment`를 직접 호출 | 세션 LLM이 실행을 거부하는 문제 |
| 분석 절차는 Hermes 스킬 | 필터와 래퍼 | 같은 이유. 스킬은 만들지 않음 |
| 허용 명령 제한(curl 하나만) | 불필요 | 세션 LLM이 명령을 실행하지 않음 |
| 저장소를 로컬에 클론해 diff 수집 | github-app이 GitHub API로 대행 | 자격 증명을 한 곳에 두고 Docker에 git이 필요 없음 |
| 세션 이름 `[PR번호-커밋ID]` | `[PR번호 - PR이름 - 커밋ID #순번]` | 같은 PR의 코멘트마다 세션이 생겨 이름이 겹침 |
| 문법 두 가지 | 세 가지(`/qa free:` 추가) | 보고서와 상관없는 대화가 필요 |
| `/ask` 별도 명령 | `/qa free:` | 사용자 선택 |

## 확인된 사실

- Hermes 웹훅은 `POST /webhooks/{route}`로 받고, 라우트는 `events`, `secret`(필수), `prompt`, `skills`, `deliver`, `script`를 가집니다. 서명 검증은 `X-Hub-Signature-256`, `X-Webhook-Signature-V2`(+`X-Webhook-Timestamp`), 구형 `X-Webhook-Signature`, GitLab, Linear, Svix를 인식합니다.
- 라우트의 `script`는 stdin으로 페이로드를 받고, 빈 출력이나 `[SILENT]`나 0이 아닌 종료 코드로 요청을 버립니다(버려진 요청은 LLM 비용 0). `events` 필터는 `X-GitHub-Event` 헤더를 씁니다. 스크립트는 `$HERMES_HOME/scripts/` 안의 파일만 허용되고 심볼릭 링크는 거부됩니다. 기본 제한 시간 30초.
- 웹훅 세션 이름은 `webhook:{route}:{deliveryId}`로 코드에 고정되어 요청마다 세션이 생깁니다(동시 요청이 서로 기다리지 않게 하려는 설계). 설정으로 바꿀 수 없습니다.
- Hermes는 하위 프로세스(필터 스크립트, 터미널 도구)의 환경 변수에서 자신의 비밀을 걸러 내며, `terminal.env_passthrough`에 이름을 등록하면 넘깁니다.
- 게이트웨이는 프로세스 환경 변수 `HERMES_SESSION_ID`를 마지막 세션 값으로 덮어씁니다. 세션 밖 프로세스가 믿으면 안 됩니다.
- Hermes 세션의 LLM은 `SOUL.md`의 보안 서약 때문에 자동화 요청을 가끔 거부합니다.
- 내장 `deliver` 대상은 telegram, discord, slack, `github_comment`(gh CLI) 등이며 임의 HTTP 콜백은 없습니다. 이 PC에는 gh CLI가 없습니다.
- `hermes project`는 폴더를 `projects.db`에 등록할 뿐 웹훅과 연결되지 않습니다. Hermes의 `skills/github/` 스킬은 재사용하지 않았습니다.
- Claude Code: `--tools ""`로 도구 없이 실행, `--json-schema`로 출력 검증, `--bare`는 구독 로그인을 읽지 않아 부적합. 네트워크 차단 옵션은 없고 도구를 주지 않는 것으로 대신합니다.
- Docker 이미지(`HERMES_HOME=/opt/data`)에는 python3, curl, bash, git이 있고 pnpm과 Claude Code CLI는 없습니다. systemd가 없습니다.

## `$HERMES_HOME`에 생긴 파일

| 항목 | 종류 | 판단 |
| --- | --- | --- |
| `config.yaml` (webhook, auxiliary 18개, 제목 끔, `terminal.env_passthrough`) | 사용자 설정 | 필요. 프로젝트에 넣지 않음 |
| `config.yaml.bak.pre-webhook/pre-auxiliary/pre-title-off/pre-passthrough.20261013` | 백업 4개 | 설정이 안정되면 지워도 됨 |
| `.env` (`TESTGATE_GITHUB_APP_SECRET` 한 줄, 사용자가 추가) | 비밀 | 필요. 이 프로젝트는 읽거나 쓰지 않음 |
| `webhook_subscriptions.json` | 라우트와 서명 키 (Hermes 관리) | 필요 |
| `testgate.json` | 허용 계정과 분석 설정 | 필요. 프로젝트에 넣지 않음 |
| `scripts/testgate_qa_filter.py`, `testgate/lib/testgate/`, `testgate/testgate-run` | 설치본 15개 | 필요. 원본은 이 레포, `install.sh`로 설치 |
| `testgate/requests/`, `reports/`, `threads/` | 실행 중 생기는 데이터 | 30일 뒤 자동 삭제 |
| `state.db`의 webhook 세션 13건 (mock 5건 포함) | 시험 기록 | 정리 가능 |

## 설계 메모

감지 경로: GitHub은 코멘트를 해석하지 않고 구독한 이벤트를 전부 보냅니다. `/qa`를 알아보는 것은 Hermes 라우트의 필터이고, 통과한 요청만 래퍼가 처리합니다. 코멘트 후 분석 시작까지 github-app의 20초 폴링 때문에 최대 약 20초가 걸립니다.

결과 반환: 래퍼가 github-app `/api/comment`를 서명해서 호출하고 github-app이 Bot 이름으로 게시합니다(`deliveryId`로 중복 방지). 세부 설계는 `docs/design-analysis.md`.

## 보안 체크리스트

- 웹훅 수신 포트(`127.0.0.1:8644`)를 외부에 노출하지 않습니다. 외부 접점은 Cloudflare Worker 하나입니다.
- 모든 라우트에 HMAC secret을 설정하고 `INSECURE_NO_AUTH`를 쓰지 않습니다.
- 입력(QA 서술, PR 설명, diff, 지식 문서, 이전 기록)은 모두 비신뢰 데이터로 난수 구분자 안에 넣습니다. 서술 본문은 Hermes 세션 LLM에 전달하지 않습니다(파일로만).
- Claude Code에는 도구를 주지 않습니다. Hermes 세션에도 도구를 주지 않습니다.
- 모델 출력은 스키마로 받고 코드가 다시 검증하며 마크다운은 코드가 만듭니다. 멘션, HTML, 이미지와 링크 문법을 무력화합니다.
- 설정 파일(`testgate.json`)이 없거나 잘못되면, 래퍼가 없으면 모두 거부합니다(fail closed).
- 요청, 보고서, 기록 파일은 권한 600입니다. 비밀은 이 저장소와 문서에 쓰지 않습니다.
- 앱 자신이 쓴 코멘트로 인한 무한 반복은 github-app이 Bot 이벤트를 sink로 보내지 않는 것으로 막습니다(실제 확인).
