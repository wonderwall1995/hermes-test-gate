"""diff 예산 배분. 파일마다 전체, 일부, 미확인 중 무엇으로 읽을지 결정적으로 정한다.

판독 범위 (coverage):
  full    diff 전체를 읽는다.
  partial 일부만 읽는다. 너무 큰 파일은 앞뒤만.
  unseen  diff를 읽지 못한다. 예산을 넘었거나 이진 파일이거나 GitHub이 diff를 주지 않은 경우.
  excluded 제외 규칙(생성물, 락 파일, 사용자가 추가한 패턴)에 해당해 분석 대상에서 뺀다. 내용을 읽지도 판정하지도 않는다.

예산을 선착순으로 쓰면 앞쪽의 큰 생성물이 예산을 먼저 소진해서 뒤쪽의 중요한 소스 파일이 잘린다.
그래서 생성물은 제외하고, 소스와 테스트와 설정을 먼저, 문서를 그다음에 채운다.
이 모듈은 Claude를 부르지 않고 같은 입력에는 항상 같은 결과를 낸다.
"""

import fnmatch

from testgate import diffsource, ledger

DEFAULT_RULES = {
    "max_diff_chars": 400000,   # 한 번에 읽는 diff 전체 상한 (12.8만 자를 59초에 처리한 실측 기준으로 올림)
    "per_file_chars": 20000,    # 파일 하나의 상한. 넘으면 앞뒤만 읽는다
    "summary_globs": [],        # 생성물로 취급할 경로 패턴 (사용자 추가)
    "full_globs": [],           # 요약하거나 자르지 않고 전체로 읽을 경로 패턴 (사용자 덮어쓰기)
}

OVERSIZED_HEAD_LINES = 80
OVERSIZED_TAIL_LINES = 30
OVERSIZED_MAX_CHARS = 8000

GENERATED_NAMES = frozenset({
    "pnpm-lock.yaml", "package-lock.json", "yarn.lock", "npm-shrinkwrap.json", "bun.lockb",
    "cargo.lock", "poetry.lock", "pipfile.lock", "uv.lock", "go.sum", "composer.lock",
    "gemfile.lock", "podfile.lock", "pubspec.lock", "flake.lock", "mix.lock", "packages.lock.json",
    "package.resolved",
})
GENERATED_SUFFIXES = (
    ".min.js", ".min.css", ".map", ".snap", ".lock", ".pb.go", "_pb2.py", "_pb2.pyi",
    ".generated.ts", ".generated.js", ".g.dart", ".designer.cs",
)
GENERATED_DIRS = frozenset({
    "node_modules", "dist", "build", "vendor", "__generated__", "generated", ".next", ".nuxt",
    "coverage", "__snapshots__",
})
DOC_SUFFIXES = (".md", ".mdx", ".rst", ".txt")

REASON_LABELS = {
    "generated": "제외 규칙에 해당(생성물·락 파일 등)",
    "oversized": "파일이 커서 앞뒤만 읽음",
    "budget": "diff 예산을 넘어 읽지 못함",
    "binary": "이진 파일이라 diff가 없음",
    "missing": "GitHub가 이 파일의 diff를 주지 않음(이진 파일이거나 너무 큰 변경)",
    "cap": "github-app의 한 번에 보내는 크기 상한으로 받지 못함",
}
UNSEEN_GUIDANCE = {
    "budget": "범위를 좁혀(`/qa [커밋ID] ...`) 다시 요청하면 읽을 수 있습니다.",
    "binary": "직접 확인한 내용을 서술에 적어 주세요.",
    "missing": "직접 확인한 내용을 서술에 적어 주세요.",
    "cap": "범위를 좁혀(`/qa [커밋ID] ...`) 다시 요청하면 읽을 수 있습니다.",
}


def rules_from(settings):
    """설정 사전에서 예산 규칙만 뽑는다. 없는 값은 기본값을 쓴다."""
    rules = dict(DEFAULT_RULES)
    for key in DEFAULT_RULES:
        if settings and settings.get(key) is not None:
            rules[key] = settings[key]
    return rules


def _matches(path, patterns):
    name = path.rsplit("/", 1)[-1]
    return any(fnmatch.fnmatch(path, p) or fnmatch.fnmatch(name, p) for p in patterns)


def classify(path, rules):
    """'generated', 'doc', 'normal' 중 하나. 경로만 보고 정한다 (중요도 판단이 아니라 구조 분류)."""
    lowered = path.lower()
    name = lowered.rsplit("/", 1)[-1]
    parts = lowered.split("/")
    if (
        name in GENERATED_NAMES
        or name.endswith(GENERATED_SUFFIXES)
        or any(part in GENERATED_DIRS for part in parts[:-1])
        or (name.endswith(".sql") and "migrations" in parts[:-1])
        or _matches(path, rules["summary_globs"])
    ):
        return "generated"
    if name.endswith(DOC_SUFFIXES) or parts[0] == "docs":
        return "doc"
    return "normal"


def is_binary(block):
    head = "\n".join(block.split("\n", 6)[:6])
    return "Binary files " in head or "GIT binary patch" in block[:2000]


def render_partial(block, head_lines, tail_lines, max_chars, reason, additions, deletions):
    """헤더와 앞부분(그리고 뒷부분)만 남기고 중간을 표시와 함께 생략한다."""
    lines = block.splitlines(keepends=True)
    first_hunk = next((i for i, ln in enumerate(lines) if ln.startswith("@@")), len(lines))
    header, body = lines[:first_hunk], lines[first_hunk:]
    head = body[:head_lines]
    tail = body[len(body) - tail_lines:] if tail_lines and len(body) > head_lines + tail_lines else []
    omitted = len(body) - len(head) - len(tail)
    marker = f"@@ [testgate] 중간 {omitted}줄 생략 (총 +{additions} -{deletions}, {REASON_LABELS[reason]}) @@\n"
    text = "".join(header + head) + (marker if omitted > 0 else "") + "".join(tail)
    if len(text) > max_chars:
        # 줄이 아주 길어서 줄 수 제한만으로는 줄어들지 않는 경우
        cut = f"@@ [testgate] 문자 수 상한으로 뒤쪽 생략 (총 +{additions} -{deletions}, {REASON_LABELS[reason]}) @@\n"
        text = text[:max_chars].rstrip("\n") + "\n" + cut
    return text


def apply(context, settings=None):
    """맥락의 diff를 예산 안에서 다시 배분한다.

    각 파일에 coverage(full/partial/unseen), reason, fp(전체 diff의 지문), chars를 붙이고,
    diff는 읽기로 한 파일의 본문만 남긴다. 지문은 줄여 담기 전의 전체 diff로 계산하므로
    같은 파일은 언제나 같은 지문을 갖는다 (PR 대화 기록의 이어받기가 이것을 쓴다).
    """
    rules = rules_from(settings)
    blocks = diffsource.blocks_by_path(context["diff"])
    scope, commit = context.get("scope", "pr"), context.get("commit")
    items = []
    for index, original in enumerate(context["files"]):
        f = dict(original)
        path = f["path"]
        block = blocks.get(path)
        incoming = f.get("diff_included", True)
        f["fp"] = ledger.fingerprint(scope, commit, block) if (block is not None and incoming) else None
        f["chars"] = len(block) if block is not None else 0
        text, coverage, reason, tier = None, "unseen", ("cap" if f.get("omitted") == "size_cap" else "missing"), 0
        forced_full = _matches(path, rules["full_globs"])
        category = "normal" if forced_full else classify(path, rules)
        if category == "generated":
            # 제외 규칙에 걸린 파일은 본문을 받지 않았어도 제외로 센다 (단계식 가져오기는 이런 파일을 받지 않는다)
            coverage, reason = "excluded", "generated"
        elif block is not None and incoming:
            if is_binary(block):
                reason = "binary"
            elif len(block) > rules["per_file_chars"] and not forced_full:
                text = render_partial(block, OVERSIZED_HEAD_LINES, OVERSIZED_TAIL_LINES, OVERSIZED_MAX_CHARS,
                                      "oversized", f.get("additions", 0), f.get("deletions", 0))
                coverage, reason, tier = "partial", "oversized", 1 if category == "doc" else 0
            else:
                text, coverage, reason, tier = block, "full", "", 1 if category == "doc" else 0
        items.append({"index": index, "file": f, "text": text, "coverage": coverage, "reason": reason, "tier": tier})

    # 우선순위(소스, 문서) 순서로 예산을 채운다. 같은 순위 안에서는 작은 파일부터 담는다.
    # 경로(알파벳) 순서로 담으면 앞쪽 폴더의 큰 파일 몇 개가 예산을 다 써서 뒤쪽 폴더의 파일이 통째로 사라진다.
    total = 0
    for item in sorted((i for i in items if i["text"] is not None), key=lambda i: (i["tier"], len(i["text"]), i["index"])):
        if total + len(item["text"]) <= rules["max_diff_chars"]:
            total += len(item["text"])
        else:
            item.update(text=None, coverage="unseen", reason="budget")

    files, kept = [], []
    counts = {"full": 0, "partial": 0, "unseen": 0, "excluded": 0}
    for item in items:  # 원래 순서로 되돌려 담는다
        f = item["file"]
        f.update(coverage=item["coverage"], reason=item["reason"], diff_included=item["text"] is not None)
        counts[item["coverage"]] += 1
        if item["text"] is not None:
            kept.append(item["text"])
        files.append(f)
    return dict(context, files=files, diff="".join(kept),
                truncated=bool(context.get("truncated")) or counts["partial"] + counts["unseen"] > 0,
                coverage=counts, diff_budget=rules["max_diff_chars"], diff_used=total)


def paths_to_fetch(files, settings=None):
    """단계식 가져오기에서 본문을 받을 파일. 제외 규칙에 걸린 파일과 GitHub이 본문을 주지 않은 파일은 받지 않는다."""
    rules = rules_from(settings)
    wanted = []
    for f in files:
        if f.get("omitted") == "no_patch":
            continue
        if not _matches(f["path"], rules["full_globs"]) and classify(f["path"], rules) == "generated":
            continue
        wanted.append(f["path"])
    return wanted


def rules_text(settings=None):
    """현재 제외 규칙을 사람이 읽는 문장으로. 자유 대화 프롬프트와 안내 문서가 같이 쓴다."""
    rules = rules_from(settings)
    lines = [
        "Excluded from analysis by default (generated files, never read or judged):",
        "- lock files: " + ", ".join(sorted(GENERATED_NAMES)),
        "- suffixes: " + ", ".join(GENERATED_SUFFIXES),
        "- directories: " + ", ".join(sorted(GENERATED_DIRS)),
        "- .sql files under a migrations directory",
        "Extra exclude patterns (testgate.json analysis.summary_globs): " + (", ".join(rules["summary_globs"]) or "(none)"),
        "Patterns always read in full (analysis.full_globs): " + (", ".join(rules["full_globs"]) or "(none)"),
        "Per-file cap: %d chars, total diff budget: %d chars." % (rules["per_file_chars"], rules["max_diff_chars"]),
        "Rules can be changed only by the operator editing testgate.json; comments cannot change them.",
    ]
    return "\n".join(lines)


def coverage_of(file_info):
    """파일의 판독 범위. 예산 모듈을 거치지 않은 옛 맥락은 diff_included로 판단한다."""
    if file_info.get("coverage"):
        return file_info["coverage"]
    return "full" if file_info.get("diff_included", True) else "unseen"


def reason_label(reason):
    return REASON_LABELS.get(reason, reason or "")
