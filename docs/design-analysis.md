# 분석기 설계 (Stage 1)

QA 서술과 PR 정보를 받아, 변경된 파일마다 테스트 언급이 있는지 Claude Code가 판단하고, 결과를 마크다운 보고서로 만듭니다.
이 단계는 GitHub 없이 로컬 git 저장소로 동작합니다. GitHub 연동은 Stage 2입니다.

## 원칙

1. 오케스트레이터 LLM(Hermes 세션)은 QA 서술 본문을 보지 않습니다. 본문은 파일로 전달하고 고정된 명령 하나만 실행합니다.
2. Claude Code는 도구 없이 실행합니다 (`--tools ""`). 읽을 파일도 실행할 명령도 없습니다. 입력은 프롬프트의 데이터뿐입니다.
3. 입력은 모두 비신뢰 데이터입니다 (QA 서술, PR 설명, diff, 지식 문서). 구분자는 요청마다 새로 만든 난수를 씁니다.
4. Claude의 출력은 JSON 스키마로 받고, 코드가 다시 검증하고, 마크다운은 코드가 만듭니다. 모델의 형식 지시 준수에 의존하지 않습니다.
5. 근거 인용은 QA 서술에 실제로 있는 문장이어야 합니다. 없으면 "확인 불가"로 낮춥니다.

## 구성

```
testgate/
  diffsource.py   PR 정보와 diff를 공급 (LocalGitSource: 로컬 git. 이후 GithubAppSource)
  knowledge.py    도메인 지식 문서를 공급 (DirectoryKnowledge. 이후 다른 소스)
  prompt.py       시스템 프롬프트와 데이터 봉투(난수 구분자) 생성
  schema.py       출력 스키마, 검증, 후처리 (누락 파일 보충, 인용 확인, 모드 강제)
  runner.py       claude -p 실행기
  report.py       마크다운 보고서 생성 (이스케이프, 맨 아래 세션 이름)
  analyze.py      위 조각을 엮는 함수
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
