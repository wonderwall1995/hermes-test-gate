# user-todo

사용자가 직접 해야 하는 일의 목록입니다. 작성은 LLM이 하고, 완료 표시는 사용자가 합니다.

## 입력 규칙 (twoline)

- 항목 하나는 정확히 두 줄입니다. 첫 줄은 이유, 둘째 줄은 할 일입니다.
- 첫 줄은 `[ ] 이유:` 또는 `[x] 이유:`로 시작합니다. 둘째 줄은 들여쓰기 4칸 뒤 `할일:`로 시작합니다.
- 각 줄은 한 문장입니다. 앞뒤 맥락을 몰라도 읽히도록 대상의 이름과 위치를 모두 씁니다.
- 영역은 `할 일`, `나중에 할 일`, `완료` 세 개입니다. 항목은 상태에 따라 영역을 옮깁니다.
- 완료한 항목은 지우지 않고 `완료` 영역으로 옮기고, 결과는 둘째 줄 끝에 괄호로 적습니다.

## 할 일

[ ] 이유: 보고서 보관소는 github-app 브랜치(fix/report_storage)와 Cloudflare Worker 변경이 함께 배포되어야 하고, Cloudflare 로그인과 sudo 비밀번호는 사용자만 쓸 수 있습니다.
    할일: github-app 에서 git push -u origin fix/report_storage 후 PR 을 병합하고, pnpm db:migrate, pnpm deploy:worker, pnpm svc:deploy 를 차례로 실행한 뒤 알려주세요. 그러면 제가 testgate.json 에서 upload_report 를 켜고 시험합니다.

[ ] 이유: 큰 파일 알림과 E2 실험에는 Hermes 에 에이전트 없이 Discord 로 보내는 라우트(deliver_only)가 하나 더 필요하고, 라우트 생성과 서명 키 설정은 사용자 몫입니다.
    할일: 단계 D 를 시작할 때 제가 라우트 생성 명령과 환경 변수 이름을 안내하므로, 그때 hermes webhook subscribe 로 testgate-notify 라우트를 만들고 키를 ~/.hermes/.env 에 넣어 주세요.

[ ] 이유: 분석을 세션 LLM이 아니라 필터가 시작하도록 바꾼 뒤에는 실제 GitHub 코멘트가 한 건도 처리되지 않았고 mock 시험만 통과했으며, 실제 PR에 Bot 코멘트가 달리는 외부 게시라 사용자가 직접 시작해야 합니다.
    할일: 테스트 PR 에 1) /qa 로 시작하는 평가 코멘트, 2) 이어서 다른 파일을 서술한 /qa 코멘트, 3) /qa free: 로 시작하는 질문 코멘트를 차례로 쓰고, 코멘트마다 Bot 응답이 달리는지와 세션 이름의 순번(#1, #2)을 알려주세요.

[ ] 이유: 수정 전에 세션 LLM이 실행을 거부해서 분석되지 않은 코멘트(hermes-test-gate PR #3의 "/qa 한 번 이거 분석해봐.")가 응답 없이 남아 있고, 다시 분석하면 그 PR에 Bot 코멘트가 실제로 게시됩니다.
    할일: 그 코멘트를 지금 다시 분석해서 PR #3 에 게시할지, 그냥 두고 새로 코멘트를 쓸지 정해 주세요.

[ ] 이유: 로그에 google/gemini-3.6-flash 유료 모델 경고가 1회 남아 있는데 실제 호출 여부는 OpenRouter 쪽 기록에만 있어 LLM이 확인할 수 없습니다.
    할일: OpenRouter 의 사용량(Activity) 페이지에서 오늘 google/gemini 모델 사용 내역이 있는지 확인하고 알려주세요.

[ ] 이유: scripts/__pycache__/qa_filter.cpython-314.pyc 가 커밋에 들어 있어 변경 이력과 병합 충돌에 계속 끼어들고, 추적 해제는 저장소 이력을 바꾸는 커밋이라 사용자 승인이 필요합니다.
    할일: 추적 해제 커밋(git rm --cached)을 LLM이 만들어도 되는지 알려주세요. 만들면 푸시는 사용자가 합니다.

[ ] 이유: 코멘트에서 Hermes 도착까지 12~22초가 걸리는 이유가 github-app이 20초마다 Worker를 확인하는 방식이고, 그 간격은 github-app의 .env 로만 바꿀 수 있습니다.
    할일: github-app 의 .env 에서 WORKER_POLL_INTERVAL_MS 를 5000~10000(밀리초)으로 정하고 pnpm svc:restart 를 실행해 주세요. 먼저 Cloudflare 대시보드에서 Worker 요청 수와 무료 한도를 확인하세요 (5초 간격이면 하루 약 17,000건).

[ ] 이유: Hermes가 TestGate 안내 문서(~/.hermes/testgate/README.md)를 실제로 찾아 읽고 정확히 답하는지는 Hermes 쪽에서 직접 물어봐야만 확인되며, 이전에는 프로젝트를 못 찾고 틀린 전제로 답했습니다.
    할일: Discord 에서 Hermes 에게 "~/.hermes/testgate/README.md 를 읽고, 분석 비용을 누가 쓰는지와 Hermes 세션이 거부해도 분석이 되는 이유를 설명해봐"라고 묻고 답이 문서와 맞는지 알려주세요.

## 나중에 할 일

[ ] 이유: 도메인 지식 문서(diagnosis.json 등)를 분석에 연결하려면 문서의 실제 형식과 위치를 알아야 합니다.
    할일: 급하지 않음. 그런 문서가 있다는 것만 알려 둔 상태이며, 연결을 시작할 때 diagnosis.json 예시 한 개와 위치를 알려주세요.

[ ] 이유: Slack에서도 분석을 요청하고 결과를 받으려면 Slack Bot이 있어야 하며, 당장 만들 계획은 없습니다.
    할일: Slack 연동을 시작할 때 개인 채널에 Bot을 만들고 토큰을 발급하세요.

[ ] 이유: 설정을 바꿀 때마다 ~/.hermes 에 config.yaml 백업 4개(config.yaml.bak.pre-*)와 시험용 mock 세션 5건이 쌓였고, 설정이 안정되면 필요 없어집니다.
    할일: 설정이 안정되었다고 판단되면 백업과 mock 세션을 지워도 되는지 알려주세요. (급하지 않음)

## 완료

[x] 이유: 수정한 코멘트에 넣은 @멘션이 알림을 보내는지는 사용자 계정의 알림함에서만 볼 수 있고, 안 보내면 결과가 나와도 알림이 없습니다 (E1 실험).
    할일: 테스트 PR 에 /qa 코멘트를 쓰고, 결과가 확인 코멘트로 바뀐 뒤 GitHub 알림(웹 알림이나 메일)이 오는지 알려주세요. 오지 않으면 ~/.hermes/testgate.json 의 analysis 에 "notify_with_new_comment": true 를 추가하면 됩니다. (결과: 멘션이 붙었고 수정 시점에 GitHub 알림이 도착함, 추가 알림 코멘트 불필요, 사용자 확인 2026-11-09)

[x] 이유: "context missing"(diff 상한 때문에 PR #1의 파일 13개를 못 봄) 보완 작업은 기존 main 과 분리된 브랜치에서 해야 합니다.
    할일: fix/context-missing 브랜치를 만들고 보완 방향을 정해 주세요. (결과: 브랜치 생성, 설계서 모드 유지 + 제약, 코드 중개 + Discord 알림, 4단계 계획 승인, 2026-11-09)

[x] 이유: Hermes 수신부에서만 보이는 관찰(세션 LLM 거부 등)은 LLM 이 직접 볼 수 없습니다.
    할일: Hermes 의 DeepSeek 으로 편지(Hermes-11.09-letter.md)를 쓰게 하고 대조를 요청해 주세요. (결과: 편지와 대조 완료, 새로 필요한 작업은 없었고 기록은 llms-todo.md 에 반영, 2026-11-09)

[x] 이유: 0단계(조용한 실패 수정)는 저장소 이력을 바꾸는 커밋이라 사용자가 확인한 뒤 해야 합니다.
    할일: 0단계 변경을 검토하고 직접 커밋해 주세요. (결과: 사용자가 검토 후 커밋하기로 결정, 11.09-session.md 와 Hermes-11.09-letter.md 는 커밋 제외)

[x] 이유: 분석 요청을 허용할 계정을 필터 스크립트에 적으려면 GitHub 로그인 ID가 필요합니다.
    할일: /qa 코멘트를 쓸 본인 GitHub 로그인 ID를 채팅으로 알려주세요. (결과: <GitHub 계정>)

[x] 이유: 분석은 Claude Code의 구독 로그인으로 실행되므로 Hermes를 실행하는 계정에서 로그인이 유효해야 합니다.
    할일: Hermes를 실행하는 계정(<사용자 계정>)의 터미널에서 claude를 실행해 로그인된 상태인지 확인하세요. (결과: 사용자가 로그인된 상태로 알고 있음, LLM은 직접 확인하지 않음)

[x] 이유: github-app이 Hermes로 이벤트를 보내는 주소(HTTP_SINK_URL)가 지금 비어 있는지 LLM은 비밀 파일이라 읽을 수 없습니다.
    할일: github-app의 .env에서 HTTP_SINK_URL 값이 비어 있는지 확인해 알려주세요. (결과: 비어 있음, 사용자가 확인)

[x] 이유: GitHub이 코멘트 이벤트를 보내지 않으면 Hermes가 /qa 코멘트를 볼 수 없습니다.
    할일: GitHub의 Settings, Developer settings, GitHub Apps, 해당 앱, Permissions & events 화면에서 Issue comment 이벤트 구독이 켜져 있는지 확인하세요. (결과: 정상 작동, 세팅 완료, 사용자 확인)

[x] 이유: Bot이 PR에 결과 코멘트를 쓰려면 쓰기 권한이 필요합니다.
    할일: 같은 화면에서 Pull requests와 Issues 권한이 Read and write인지 확인하고, 바꿨다면 설치된 계정에서 변경 승인을 누르세요. (결과: 정상 작동, 세팅 완료, 사용자 확인)

[x] 이유: GitHub App이 설치되지 않은 레포에서는 이벤트가 오지 않습니다.
    할일: 해당 앱의 Install App 화면에서 hermes-test-gate 레포가 접근 대상에 포함되어 있는지 확인하세요. (결과: 정상 작동, 세팅 완료, 사용자 확인)

[x] 이유: github-app 서비스가 새 헤더로 동작하려면 재시작이 필요한데, 재시작에는 sudo 비밀번호가 필요해서 LLM이 실행할 수 없습니다.
    할일: 터미널에서 github-app 폴더로 이동해 pnpm svc:restart를 실행하고 active 표시가 나오는지 알려주세요. (결과: 재시작 완료, active, healthz 정상, 사용자 실행)

[x] 이유: github-app 레포를 공개할 때 커밋 기록에 개인 이메일과 Cloudflare 서브도메인이 이미 들어 있어 공개 후에는 지우기 어렵습니다.
    할일: 아래 3건을 어떻게 처리할지 채팅으로 정해 주세요. (1) 커밋 작성자 이메일 <이메일 앞부분> 계정 2건, (2) 문서 2곳의 workers.dev 주소, (3) worker/wrangler.toml의 D1 database_id. (결과: 이메일과 database_id는 그대로 두기로 결정, workers.dev 주소는 LLM이 파일에서 교체함)

[x] 이유: Hermes 단독으로 필터와 서명 검증이 동작하는지, 특히 에이전트를 실제로 시작하는 qa 케이스는 LLM이 비용 때문에 실행하지 않았습니다.
    할일: ~/.hermes/projects/hermes-test-gate/docs/mock-test.md 의 1단계를 따라 터미널 1에서 pnpm gateway:logs 를 켜 두고 터미널 2에서 pnpm mock:qa 를 실행한 뒤 HTTP 응답과 로그를 알려주세요. (결과: HTTP 202 accepted, 세션 생성, 응답 RECEIVED, 사용자 실행)

[x] 이유: github-app이 Hermes로 이벤트를 보내려면 .env에 수신 주소와 서명 키가 있어야 하고, .env는 비밀 파일이라 LLM이 수정하지 않기로 했습니다.
    할일: github-app의 .env에 HTTP_SINK_URL=http://127.0.0.1:8644/webhooks/github-app 과 HTTP_SINK_SECRET=(라우트의 secret, 전달용 파일은 이후 삭제됨)을 넣고 pnpm svc:restart를 실행하세요. (결과: 설정과 재시작 완료, .env 백업함, github-app 로그에서 http sink 활성화 확인)

[x] 이유: github-app을 거친 실제 경로(GitHub 코멘트에서 Hermes까지)는 사용자의 PR이 있어야 확인할 수 있습니다.
    할일: docs/mock-test.md 의 2단계대로 테스트용 PR에 일반 코멘트 test 와 /qa test 를 차례로 쓰고 결과를 알려주세요. (결과: 성공. PR #3 코멘트 test는 무시, /qa test는 세션 생성, 사용자 실행 2026-10-13 11:56~11:58)

[x] 이유: 분석에 쓸 Claude 모델에 따라 호출당 비용과 품질이 달라지고 기본값은 가장 비싼 Opus입니다 (시험은 sonnet, 호출당 목록가 약 $0.02).
    할일: 분석에 쓸 모델(예: sonnet, opus)을 정해 알려주세요. 정하면 testgate.json 의 analysis.claude_model 에 적습니다. (결과: sonnet 5.5, 추론 강도 medium. testgate.json 의 analysis 에 적용함)

[x] 이유: Hermes가 github-app의 PR 조회와 코멘트 API를 호출하려면 두 쪽의 서명 키가 같아야 하고, github-app의 .env 는 비밀 파일이라 LLM이 수정하지 않기로 했습니다.
    할일: github-app 의 .env 에 HERMES_API_SECRET=(서명 키) 한 줄을 추가하세요. (결과: 사용자가 추가함)

[x] 이유: Hermes가 github-app의 API를 부를 때 쓰는 서명 키는 프로젝트가 아니라 Hermes의 자격 증명 저장소(.env)에 있어야 하고, 그 파일은 비밀 파일이라 LLM이 수정하지 않기로 했습니다.
    할일: ~/.hermes/.env 에 TESTGATE_GITHUB_APP_SECRET=(github-app 의 .env 에 넣은 HERMES_API_SECRET 과 같은 값) 한 줄을 추가하고 알려주세요. 그러면 제가 게이트웨이를 재시작합니다. (결과: 사용자가 추가함, 래퍼가 값을 받는 것을 확인)

[x] 이유: 새 API 코드는 빌드가 끝났지만 실행 중인 github-app 서비스는 아직 옛 코드이고 재시작에는 sudo 비밀번호가 필요합니다.
    할일: .env 를 고친 뒤 github-app 폴더에서 pnpm svc:restart 를 실행하고 active 가 나오면 알려주세요. (결과: 13:07 재시작 확인, API 열림)

[x] 이유: GitHub에서 Hermes까지 이어지는 전체 경로와 Bot 코멘트 게시는 실제 PR 코멘트로만 확인할 수 있고, 되돌리기 어려운 외부 게시라 사용자가 직접 시작해야 합니다.
    할일: github-app 레포의 PR #3(또는 원하는 테스트 PR) 대화창에 /qa 로 시작하는 코멘트(예: /qa 나는 로그를 확인했고 다른 테스트는 하지 않았다)를 쓰고, 약 30초 뒤 PR 에 Bot 코멘트가 달리는지 알려주세요. (결과: 성공. hermes-test-gate PR #2 에 코멘트, 약 64초 뒤 Bot 코멘트 게시 확인)

[x] 이유: 판정 기준이 없으면 합격과 불합격을 나눌 수 없습니다.
    할일: 테스트 커버리지 충족을 어떻게 판단할지(예: 변경된 파일마다 체크리스트 항목 1개 이상) 정해서 알려주세요. (결과: 합격 점수 없이 파일마다 서술에 테스트 언급이 있는지 보고 없으면 이행을 다시 요청하기로 결정, 2026-10-13)
