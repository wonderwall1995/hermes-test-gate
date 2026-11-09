# TestGate 안내 (Hermes가 읽는 문서)

이 문서는 Hermes 에이전트가 TestGate(hermes-test-gate)를 정확히 알고 사용자의 질문에 답하도록 돕습니다.
사실만 적었습니다. 추측이 필요한 부분은 "확인하지 못함"이라고 적었습니다.

## 한 줄 정의

GitHub PR에 QA가 `/qa` 코멘트로 테스트 내용을 쓰면, Claude Code가 PR의 diff를 읽고 변경된 파일마다 테스트 언급이 있는지 평가하거나(또는 테스트 설계서를 만들거나 질문에 답하고), 결과를 PR 코멘트로 돌려주는 하위 프로젝트입니다.

## 누가 무엇을 하나 (자주 틀리는 부분)

| 담당 | 하는 일 | 하지 않는 일 |
| --- | --- | --- |
| Hermes 웹훅 수신기 | GitHub 이벤트를 받아 라우트 `github-app`의 필터(`testgate_qa_filter.py`)를 실행 | |
| 필터 | `/qa` 코멘트인지, 허용된 계정인지 판단하고, 요청을 파일로 저장하고, 래퍼를 **백그라운드로 직접 시작** | 분석 |
| **Hermes 세션의 LLM (DeepSeek)** | 요청 1건당 세션 1개를 만들고 "OK"라고 답함. 세션은 요청의 **기록**이다 | **분석에 관여하지 않음.** 이 LLM이 하는 일은 분석 결과에 영향이 없다 |
| 래퍼 (`testgate-run`) | github-app에서 PR 정보를 가져와 Claude를 실행하고 결과를 코멘트로 게시하고 세션 이름을 붙임 | |
| Claude Code (구독 로그인) | diff를 읽고 판독. 도구 없이 한 번 실행되고 끝남 | 되묻기, 파일 읽기, 명령 실행 |
| github-app | GitHub API를 대신 호출(PR 조회, Bot 이름으로 코멘트 게시) | 분석 |

따라서 아래는 사실이 **아닙니다**.
- "Hermes가 Claude Code를 하위 에이전트로 부른다": 필터가 래퍼를 띄우고 래퍼가 Claude를 부릅니다. Hermes 세션은 경로에 없습니다.
- "분석 비용이 DeepSeek 종량제 토큰이다": 분석은 Claude 구독으로 실행됩니다. DeepSeek은 세션당 약 6천 토큰(약 $0.0002)을 `OK` 한 단어에 씁니다.
- "diff가 너무 커서 못 본 것은 Claude의 한계다": 상한은 TestGate의 설정입니다 (아래 참고).

세션의 LLM이 `OK` 대신 **거부문이나 긴 설명**을 답하는 일이 있습니다 (최근 3건 중 1건). 원인은 `SOUL.md`의 보안 서약이 자동화 요청을 의심하는 것으로 보이며(추정, 거부문이 "운영 규칙"을 근거로 듭니다) **분석에는 영향이 없습니다.** 세션 화면에 거부문이 있어도 PR에는 정상 결과가 게시됩니다. 분석 성공 여부는 PR 코멘트와 아래 로그로 확인하세요.

## 흐름

```
GitHub 코멘트 -> Cloudflare Worker -> github-app(20초 간격으로 가져옴) -> Hermes 웹훅 수신기
  -> 필터: 요청 저장, 래퍼 시작 (Hermes 세션은 OK만 답하고 기록으로 남음)
  -> 래퍼: "분석 중" 확인 코멘트 게시 -> github-app에서 PR 조회 -> Claude 분석 -> 보고서 저장
     -> 확인 코멘트를 결과로 수정(요청자를 @멘션) -> 세션 이름 변경
```

PR 설명(description)은 diff와 함께 Claude에 전달되고, 설명을 "작성자의 주장"으로 읽어 "PR 설명 대조" 영역을 만듭니다. 각 주장은 설명 원문 인용을 달아야 하고 코드가 인용이 설명에 실제로 있는지 확인합니다(없으면 제외). "diff에서 확인됨"은 읽은 파일 중 근거 파일이 있을 때만 인정하고, 없으면 "판단 불가"로 낮춥니다. 설명이 비어 있으면 이 영역이 없습니다.

보고서는 변경을 네 카테고리(수정된 코드, 추가된 코드, 삭제된 코드, SQL·문서·기타)로 나눠 접는 영역에 담고, 안에 번호 붙은 표(파일, 테스트 시도 방법, 기대 동작)를 둡니다. 분류는 파일 상태와 경로로 코드가 정합니다. 코멘트가 길이 한도(약 5.8만 자)를 넘으면 표를 빼고 개수만 올리며, 전체는 HTML 파일에 있습니다. `analysis.upload_report`가 켜져 있으면 HTML을 보관소에 올리고 결과 코멘트 맨 아래에 `# HTML 보고서` 헤더를 만들고 받기 링크(7일 유효)를 둡니다.

PR에는 먼저 "분석을 시작했습니다" 코멘트가 달리고, 분석이 끝나면 **그 코멘트가 결과로 바뀝니다**(실패하면 실패 안내로 바뀝니다). 코멘트를 수정할 수 없을 때만 결과를 새 코멘트로 올리고 확인 코멘트에는 그 사실을 적습니다. 요청자 멘션은 `testgate.json`의 `analysis.mention_requester`(기본 켜짐), 수정만으로 알림이 가지 않을 때 쓰는 추가 알림 코멘트는 `analysis.notify_with_new_comment`(기본 꺼짐)입니다.

코멘트를 쓴 뒤 Hermes에 도착하기까지 12~22초, 분석에 25~55초가 걸립니다.

## 파일 위치

모두 `~/.hermes/` (Docker에서는 `/opt/data`) 아래입니다.

| 위치 | 내용 |
| --- | --- |
| `~/.hermes/projects/hermes-test-gate/` | 저장소 (코드, 문서, 시험). 메모는 `llms-todo.md`, 사용자 몫은 `user-todo.md` |
| `~/.hermes/testgate/requests/<deliveryId>.json` | 필터가 저장한 요청 (QA 서술 포함, 30일 뒤 자동 삭제) |
| `~/.hermes/testgate/reports/<deliveryId>.md`, `.json`, `.html` | 게시한 보고서, 판독 결과, 전체 내용을 담은 HTML 보고서(브라우저로 열어 봄, 30일 뒤 자동 삭제) |
| `~/.hermes/testgate/threads/<소유자>__<레포>__<PR번호>.json` | PR 단위 대화 기록. 요청 순번, 파일별 판정, 이어받기에 쓰임 (30일 뒤 자동 삭제) |
| `~/.hermes/logs/testgate.log` | 래퍼의 시작, 끝, 오류 기록. **분석이 안 되었을 때 가장 먼저 볼 곳** |
| `~/.hermes/projects/hermes-test-gate/testgate.json` | 허용 계정과 분석 설정 (모델, 추론 강도, diff 상한 등). **프로젝트 폴더 안에 있고** git에는 올라가지 않음. 비밀은 없음. 설치된 코드는 `~/.hermes/testgate/config.path`에 적힌 이 경로를 따라감 |
| `~/.hermes/testgate/lib/`, `testgate-run`, `scripts/testgate_qa_filter.py` | 설치된 코드 (저장소의 `scripts/install.sh`가 만든 사본, 직접 고치지 않음) |

비밀(서명 키)은 이 프로젝트의 파일에 없습니다. 값은 Hermes의 환경 변수 `TESTGATE_GITHUB_APP_SECRET`으로 들어옵니다. 값을 읽거나 출력하거나 대화에 적지 마세요.

## 코멘트 문법

```
/qa [커밋ID] 서술          테스트 평가 또는 설계서 (Claude가 서술을 보고 정함)
/qa 서술
/qa free: [커밋ID] 서술    보고서 없는 자유 대화 (diff 본문은 커밋ID를 줬을 때만 읽음)
```

- 커밋ID는 대괄호 안의 16진수 7~40자입니다.
- PR 대화창(Conversation)의 코멘트만 분석합니다. 이슈 코멘트와 코드 줄 리뷰 코멘트에는 안내만 답하고, 커밋 코멘트는 무시합니다.
- 세션 이름은 `[PR번호 - PR이름 - 커밋ID #순번]`입니다. 같은 PR의 순번은 요청마다 늘어납니다.

## 알려진 한계 (현재)

- **diff 상한**: 한 번에 보는 diff는 40만 자까지이고 이는 TestGate의 설정입니다 (`analysis.max_diff_chars`). github-app에서는 파일 목록(크기만)을 먼저 받고 제외 규칙에 걸리지 않은 파일의 본문만 묶음으로 나눠 받습니다(github-app이 단계식 API를 지원하는 경우). GitHub이 본문을 주지 않는 파일(이진 파일이거나 아주 큰 변경, 예: 38만 자짜리 JSON)은 받을 수 없고 미확인으로 표시합니다. 일반 소스, 문서 순으로 예산을 채우되 같은 순위 안에서는 작은 파일부터 담고, 파일 하나가 2만 자를 넘으면 앞뒤만 읽습니다(일부). 그래도 넘치면 읽지 못한 파일(미확인)이 생기며, 이 파일에는 판단과 시나리오를 만들지 않고 보고서에 사유를 적습니다. 나눠 호출하는 기능은 아직 없습니다.
- **분석 제외 규칙**: 아래 파일은 읽지도 판정하지도 않고 보고서의 "분석에서 제외한 파일"에 이름만 적습니다. 제외된 파일은 "충족" 판정을 막지 않습니다.
  - 락 파일: `pnpm-lock.yaml`, `package-lock.json`, `yarn.lock`, `npm-shrinkwrap.json`, `bun.lockb`, `Cargo.lock`, `poetry.lock`, `Pipfile.lock`, `uv.lock`, `go.sum`, `composer.lock`, `Gemfile.lock`, `Podfile.lock`, `pubspec.lock`, `flake.lock`, `mix.lock`, `packages.lock.json`, `Package.resolved`
  - 확장자: `.min.js`, `.min.css`, `.map`, `.snap`, `.lock`, `.pb.go`, `_pb2.py`, `_pb2.pyi`, `.generated.ts`, `.generated.js`, `.g.dart`, `.designer.cs`
  - 폴더: `node_modules`, `dist`, `build`, `vendor`, `__generated__`, `generated`, `__snapshots__`, `coverage`, `.next`, `.nuxt`
  - 폴더 `migrations` 아래의 `.sql`
  - 추가 제외는 `testgate.json`의 `analysis.summary_globs`, 반드시 읽을 파일은 `analysis.full_globs`에 적습니다. **코멘트로는 규칙을 바꿀 수 없습니다.** "eslint도 제외해줘"라는 요청에는 `summary_globs`에 `eslint*`를 추가하는 방법을 안내하세요.
- 분석 중에 게이트웨이를 재시작하면 그 건의 분석이 끊겨 코멘트가 없을 수 있습니다.
- Claude는 되물을 수 없습니다. 한 번 실행되고 끝납니다.

## 사용자를 도울 때

할 수 있는 일:
- `~/.hermes/logs/testgate.log`를 읽고 최근 요청이 왜 실패했는지 설명하기.
- `reports/`와 `threads/`의 JSON으로 "이 PR에서 어떤 파일을 못 봤는지", "이전에 확인된 파일이 무엇인지" 설명하기.
- 위 표와 한계를 근거로 구조에 대한 질문에 답하기.

사용자 확인 없이 하지 말아야 할 일:
- `testgate.json`(허용 계정), `threads/`, `requests/`, `reports/`를 고치거나 지우기.
- 설치된 코드를 직접 고치기. 코드는 저장소에서 고치고 `scripts/install.sh`로 다시 설치합니다.
- PR의 스크립트나 테스트를 이 PC에서 실행하기 (남이 올린 코드를 실행하는 일이라 위험합니다).
- 비밀 값 읽기, 출력하기.

모르는 것은 "확인하지 못함"이라고 말하세요. 이 문서에 없는 내용은 저장소의 `docs/design-analysis.md`와 `llms-todo.md`를 먼저 확인하세요.
