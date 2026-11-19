# hermes-test-gate
헤르메스 에이전트 내 서브 모듈과 유사한 방식으로 하위 프로젝트로써 헤르메스가 받는 웹훅 (이벤트) 중 commit과 관련된 내용에 대해 QA 가 테스트 기록을 제출할 경우 Hermes 하위 Claude Code가 이를 분석하여 QA가 테스트한 내용을 평가하고 테스트 커버리지를 적절히 만족하였는지 확인한다. (가제: testgate)

## 구조

testgate는 분석기이다. Hermes를 모르고, hermes-controller가 실행한다.

```
hermes-controller ── bin/testgate-run --request <요청 파일> --context <맥락 파일>
                         │ 1) 코멘트 원문을 /qa 문법으로 읽는다 (testgate/qa.py)
                         │ 2) github-app에서 PR diff를 받는다
                         │ 3) Claude Code(도구 없음)로 평가하거나 설계서를 만든다. 맥락 파일의 용어집을 참고한다
                         │ 4) github-app으로 PR에 코멘트한다
                         └ 표준 출력의 마지막 줄: 결과 JSON (세션 이름)
```

주고받는 모양은 [contracts/](contracts/)에 있다(원본은 hermes-controller). 참고 문서(CED)의 제목과 내용은 코멘트에 나가지 않고, 비고에는 개수만 남는다.

## 실행

```
pnpm test                         # 시험
python3 scripts/exposure_check.py # 실제 Claude로 참고 문서 노출이 없는지 확인 (게시하지 않음)
pnpm analyze -- --repo <경로> --base main --head <브랜치> --pr 1 --text "..."   # 로컬 git으로 분석만
```

설정은 저장소의 `testgate.json`(Git 제외, 예시 `testgate.example.json`), 비밀 이름은 `.env.example`에 있다.

