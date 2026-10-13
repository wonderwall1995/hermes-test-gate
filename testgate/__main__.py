"""CLI. 사용법: python3 -m testgate analyze --repo <경로> --base <참조> --head <참조> --pr <번호> ..."""

import argparse
import json
import sys

from testgate import analyze as analyze_mod
from testgate import config, diffsource, knowledge, prompt, runner, schema


def build_parser():
    parser = argparse.ArgumentParser(prog="testgate")
    sub = parser.add_subparsers(dest="command", required=True)
    r = sub.add_parser("run", help="Hermes 세션이 실행하는 래퍼. delivery ID 하나를 받는다")
    r.add_argument("delivery_id")
    a = sub.add_parser("analyze", help="QA 서술을 평가하거나 테스트 설계서를 만든다")
    a.add_argument("--repo", required=True, help="로컬 git 저장소 경로 (diff 소스)")
    a.add_argument("--base", required=True, help="기준 브랜치 또는 참조")
    a.add_argument("--head", required=True, help="PR 헤드 브랜치 또는 참조")
    a.add_argument("--pr", required=True, type=int, help="PR 번호")
    a.add_argument("--commit", help="특정 커밋 하나만 분석한다 (7~40자 16진수)")
    a.add_argument("--title", default="")
    a.add_argument("--body", default="", help="PR 설명")
    text = a.add_mutually_exclusive_group()
    text.add_argument("--text", help="QA 서술")
    text.add_argument("--text-file", help="QA 서술이 든 파일")
    a.add_argument("--repo-name", default="local/test", help="owner/name 표기")
    a.add_argument("--config", help="testgate.json 경로")
    a.add_argument("--out", help="보고서를 쓸 파일 (기본: 표준 출력)")
    a.add_argument("--json-out", help="검증된 결과 JSON을 쓸 파일")
    a.add_argument("--model", help="Claude 모델 (설정보다 우선)")
    a.add_argument("--effort", help="Claude 추론 강도: low, medium, high, xhigh, max (설정보다 우선)")
    a.add_argument("--dry-run", action="store_true", help="Claude를 실행하지 않고 입력 크기만 출력")
    return parser


def read_text(args):
    if args.text_file:
        with open(args.text_file, encoding="utf-8") as handle:
            return handle.read()
    return args.text or ""


def main(argv=None):
    args = build_parser().parse_args(argv)
    if args.command == "run":
        from testgate import run as run_mod
        return run_mod.main(args.delivery_id)
    settings = config.load_analysis_config(args.config)
    commit = args.commit.lower() if args.commit else None
    request = {"deliveryId": "local", "repo": args.repo_name, "pr": args.pr, "commit": commit, "text": read_text(args)}
    try:
        source = diffsource.LocalGitSource(args.repo, settings["max_diff_chars"])
        context = source.get(args.base, args.head, commit=commit, title=args.title, body=args.body)
        kb = knowledge.DirectoryKnowledge(settings["knowledge_dirs"]) if settings["knowledge_dirs"] else knowledge.NullKnowledge()
        if args.dry_run:
            user_prompt = prompt.build_user_prompt(request, context, kb.load(context))
            print(f"파일 {len(context['files'])}개, diff {len(context['diff'])}자, 프롬프트 {len(user_prompt)}자, 잘림={context['truncated']}")
            return 0
        claude = runner.ClaudeRunner(
            binary=settings["claude_binary"], model=args.model or settings["claude_model"],
            timeout=settings["timeout_seconds"], effort=args.effort or settings["claude_effort"],
        )
        outcome = analyze_mod.analyze(request, context, kb, claude)
    except (diffsource.DiffSourceError, prompt.PromptError, runner.RunnerError, analyze_mod.AnalysisError) as exc:
        print(f"분석 실패: {exc}", file=sys.stderr)
        return 1

    if args.out:
        with open(args.out, "w", encoding="utf-8") as handle:
            handle.write(outcome["markdown"])
    else:
        print(outcome["markdown"])
    if args.json_out:
        with open(args.json_out, "w", encoding="utf-8") as handle:
            json.dump(outcome["result"], handle, ensure_ascii=False, indent=2)
    meta = outcome["meta"]
    print(f"판정={outcome['verdict']} 모드={outcome['mode']} 세션={outcome['session_name']} "
          f"비용(목록가)={meta.get('cost_usd')} 시간ms={meta.get('duration_ms')} 모델={meta.get('models')}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
