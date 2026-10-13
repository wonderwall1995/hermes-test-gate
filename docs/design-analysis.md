# 분석기 설계 (Stage 1)

QA 서술과 PR 정보를 받아, 변경된 파일마다 테스트 언급이 있는지 Claude Code가 판단하고, 결과를 마크다운 보고서로 만듭니다.
이 단계는 GitHub 없이 로컬 git 저장소로 동작합니다. GitHub 연동은 Stage 2입니다.

## 원칙

1. Hermes 세션의 LLM은 분석에 관여하지 않습니다. 필터가 통과 판정 후 래퍼를 백그라운드로 시작하고, 본문은 파일(`requests/`)로만 전달됩니다. 세션에는 도구를 주지 않고 요청의 기록으로만 남깁니다 (LLM이 자동화 요청을 보안상 거부해 분석이 조용히 사라진 적이 있어서).
2. Claude Code는 도구 없이 실행합니다 (`--tools ""`). 읽을 파일도 실행할 명령도 없습니다. 입력은 프롬프트의 데이터뿐입니다.
3. 입력은 모두 비신뢰 데이터입니다 (QA 서술, PR 설명, diff, 지식 문서). 구분자는 요청마다 새로 만든 난수를 씁니다.
4. Claude의 출력은 JSON 스키마로 받고, 코드가 다시 검증하고, 마크다운은 코드가 만듭니다. 모델의 형식 지시 준수에 의존하지 않습니다.
5. 근거 인용은 QA 서술에 실제로 있는 문장이어야 합니다. 없으면 "확인 불가"로 낮춥니다.

## 코멘트 문법

```
/qa [커밋ID] 자유 서술          테스트 평가 또는 설계서 (Claude가 서술을 보고 모드를 정함)
/qa 자유 서술
/qa free: [커밋ID] 자유 서술    보고서 없는 자유 대화
```

- 커밋ID는 대괄호 안의 16진수 7~40자입니다. 대괄호가 없으면 전부 서술입니다.
- `free:`는 소문자와 콜론을 정확히 써야 인정합니다 (`free plan 테스트...` 같은 평가 서술이 오인되지 않게).
- `free:` 모드는 파일별 판정 표와 diff 강제 분석이 없고 답변만 코멘트로 돌려줍니다. diff 본문은 커밋ID를 줬을 때만 읽습니다. PR 제목, 설명, 변경 파일 목록, 이전 기록은 항상 줍니다.
- `free:` 뒤가 비어 있으면 Claude를 부르지 않고 사용법 안내만 답합니다.

## PR 대화 기록과 이어받기

Hermes 웹훅은 요청마다 새 세션을 만듭니다 (코드에 고정된 설계). Claude도 호출마다 새로 시작합니다. 같은 PR의 연속성은 testgate의 PR 대화 기록(`$HERMES_HOME/testgate/threads/<소유자>__<레포>__<PR번호>.json`)이 맡습니다. 소유자는 개인과 조직 모두 같은 형식입니다.

- 요청마다 순번을 정하고(파일 잠금으로 동시 요청에도 겹치지 않음), 결과와 파일별 판정과 diff 지문을 기록합니다.
- 세션 이름: `[PR번호 - PR이름 - 커밋ID #순번]`. PR이름은 40자로 줄이고 대괄호, 백틱, 줄바꿈을 없앱니다. 커밋ID는 코멘트에 있을 때만 붙습니다. PR 이름이 나중에 바뀌어도 이전 세션 이름은 바꾸지 않습니다 (그 시점의 기록이고 PR 번호가 고정 식별자). 이름 변경 이력은 기록에 남습니다.
- 이전 요청 요약은 Claude에게 비신뢰 데이터로 전달합니다.

### 확인됨 이어받기 규칙

다음 셋이 모두 맞는 파일은 이전 판정(확인됨)을 이어받고 Claude에게 평가시키지 않습니다. 판정은 코드가 합니다.
1. 이전 판정이 `yes`였다 (코드가 근거 인용을 서술에서 확인한 것).
2. 그 파일의 diff 지문(범위 포함)이 지금과 같다.
3. 같은 범위다 (PR 전체와 커밋 하나는 지문이 달라 서로 이어받지 않음).

같은 지문의 가장 최근 기록이 판단합니다. `partial`, `no`, `unclear`와 자유 대화 응답은 이어받지 않습니다. 예전에 확인됐지만 그 뒤 diff가 바뀐 파일은 이어받지 않고, 보고서 비고에 "다시 확인이 필요한 파일"로 알립니다. 평가할 파일이 하나도 남지 않으면 Claude를 부르지 않습니다 (비용 0).

## 구성

```
testgate/
  diffsource.py   PR 정보와 diff를 공급 (LocalGitSource: 로컬 git. 이후 GithubAppSource)
  knowledge.py    도메인 지식 문서를 공급 (DirectoryKnowledge. 이후 다른 소스)
  prompt.py       시스템 프롬프트와 데이터 봉투(난수 구분자) 생성
  schema.py       출력 스키마, 검증, 후처리 (누락 파일 보충, 인용 확인, 모드 강제)
  runner.py       claude -p 실행기
  report.py       마크다운 보고서 생성 (이스케이프, 맨 아래 세션 이름)
  ledger.py       PR 대화 기록, 순번, diff 지문, 이어받기 판단
  analyze.py      위 조각을 엮는 함수 (평가와 설계서, 자유 대화)
  __main__.py     CLI: python3 -m testgate analyze ...
```

표준 라이브러리만 씁니다 (Docker 이미지의 python3로 동작).

## 데이터 형태

요청 (필터가 만들고, 이후 파일로 저장):
`{"deliveryId", "repo": "owner/name", "pr": 번호, "commit": 커밋ID 또는 null, "text": 서술}`

PR 맥락 (diff 소스가 만듦):
`{"title", "body", "base_ref", "head_sha", "scope": "pr" 또는 "commit", "files": [{"path","status","additions","deletions","diff_included"}], "diff", "truncated"}`

Claude 출력 (스키마):
`mode`(evaluate 또는 design), `summary`, `changes[]`(path, change_summary, tested[yes|partial|no|unclear], evidence_quote, request, scenarios[]), `notes`

## 코드가 덮어쓰는 규칙

- 서술이 비어 있으면 mode는 항상 design입니다.
- 변경 파일 목록과 `changes[].path`가 일치해야 합니다. 빠진 파일은 `unclear`로 보충하고, 목록에 없는 경로는 버립니다.
- `tested`가 yes 또는 partial인데 `evidence_quote`가 서술에 없으면 `unclear`로 낮춥니다.
- diff가 잘려서 내용을 못 본 파일은 `unclear`입니다.
- 판정은 코드가 계산합니다: 모든 변경이 yes이면 "충족", 아니면 "추가 테스트 필요".

## 확장: 도메인 지식 문서

`KnowledgeSource`는 PR 맥락을 받아 `{id, title, text}` 목록을 돌려줍니다. 문서는 Claude에게 참고 데이터로 전달됩니다 (비신뢰 데이터로 취급).
v1은 `testgate.json`의 `analysis.knowledge_dirs`에 적힌 폴더의 `.json`, `.md` 파일을 읽습니다 (길이 상한 있음).
`diagnosis.json` 같은 도메인 사전 페이지를 쓰려면 "어떤 PR에 어떤 문서가 해당하는가"를 정해야 합니다. 이것은 미정이며 문서 형식을 확인한 뒤 정합니다.

## Stage 2 (github-app 변경이 필요한 부분, 아직 하지 않음)

- PR 정보와 diff 조회 엔드포인트 (서명된 요청, 설치 토큰 사용, 읽기 전용).
- 결과 게시 엔드포인트 (서명된 요청, `deliveryId`로 중복 방지).
