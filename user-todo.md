# user-todo

사용자가 직접 해야 하는 일의 목록입니다. 작성은 LLM이 하고, 완료 표시는 사용자가 합니다.

## 입력 규칙 (twoline)

- 항목 하나는 정확히 두 줄입니다. 첫 줄은 이유, 둘째 줄은 할 일입니다.
- 첫 줄은 `[ ] 이유:` 또는 `[x] 이유:`로 시작합니다. 둘째 줄은 들여쓰기 4칸 뒤 `할일:`로 시작합니다.
- 각 줄은 한 문장입니다. 앞뒤 맥락을 몰라도 읽히도록 대상의 이름과 위치를 모두 씁니다.
- 영역은 `할 일`, `나중에 할 일`, `완료` 세 개입니다. 항목은 상태에 따라 영역을 옮깁니다.
- 완료한 항목은 지우지 않고 `완료` 영역으로 옮기고, 결과는 둘째 줄 끝에 괄호로 적습니다.

## 할 일

[ ] 이유: 순번, 이어받기, 자유 대화는 같은 PR에 코멘트를 여러 번 써 봐야 확인되고, 실제 PR에 Bot 코멘트가 달리는 외부 게시라 사용자가 직접 시작해야 합니다.
    할일: 테스트 PR 에 1) /qa 로 시작하는 평가 코멘트, 2) 이어서 다른 파일을 서술한 /qa 코멘트, 3) /qa free: 로 시작하는 질문 코멘트를 차례로 쓰고 Bot 코멘트와 세션 이름(#1, #2)을 알려주세요.

## 나중에 할 일

[ ] 이유: 도메인 지식 문서(diagnosis.json 등)를 분석에 연결하려면 문서의 실제 형식과 위치를 알아야 합니다.
    할일: 급하지 않음. 그런 문서가 있다는 것만 알려 둔 상태이며, 연결을 시작할 때 diagnosis.json 예시 한 개와 위치를 알려주세요.

[ ] 이유: 판정 기준이 없으면 합격과 불합격을 나눌 수 없습니다.
    할일: 테스트 커버리지 충족을 어떻게 판단할지(예: 변경된 파일마다 체크리스트 항목 1개 이상) 정해서 알려주세요.

[ ] 이유: Slack에서도 분석을 요청하고 결과를 받으려면 Slack Bot이 있어야 하며, 당장 만들 계획은 없습니다.
    할일: Slack 연동을 시작할 때 개인 채널에 Bot을 만들고 토큰을 발급하세요.

## 완료

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
