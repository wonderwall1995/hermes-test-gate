"""분석기 설정. testgate.json 의 선택 항목 "analysis" 를 읽는다. 파일이 없어도 기본값으로 동작한다."""

import json
import os
import pathlib

DEFAULTS = {
    "claude_binary": "claude",
    "claude_model": None,
    "claude_effort": None,
    "timeout_seconds": 300,
    "max_diff_chars": 400000,
    "per_file_chars": 20000,
    "summary_globs": [],
    "full_globs": [],
    "knowledge_dirs": [],
    "github_app_url": "http://127.0.0.1:3200",
    "post_comments": True,
    "mention_requester": True,
    "upload_report": False,
    "notify_with_new_comment": False,
    "route_name": "github-app",
    "hermes_binary": "hermes",
    "retention_days": 30,
}


def config_path():
    """설정 파일 경로. 순서: 환경 변수 TESTGATE_CONFIG, 설치가 남긴 안내 파일(저장소 안의 경로), 홈 폴더의 testgate.json."""
    explicit = os.environ.get("TESTGATE_CONFIG")
    if explicit:
        return pathlib.Path(explicit)
    try:
        for line in (hermes_home() / "testgate" / "config.path").read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line and not line.startswith("#") and os.path.isabs(line):
                return pathlib.Path(line)
    except OSError:
        pass
    return hermes_home() / "testgate.json"


def hermes_home():
    home = os.environ.get("HERMES_HOME")
    return pathlib.Path(home) if home else pathlib.Path.home() / ".hermes"


def load_allowed_owners(path=None):
    """분석을 허용할 레포 소유자 목록. 설정이 없거나 잘못되면 빈 목록(모두 거부)이다."""
    try:
        data = json.loads(pathlib.Path(path or config_path()).read_text(encoding="utf-8"))
        owners = data.get("allowed_repo_owners")
        if isinstance(owners, list) and all(isinstance(o, str) and o for o in owners):
            return owners
    except (OSError, json.JSONDecodeError, AttributeError):
        pass
    return []


def load_analysis_config(path=None):
    settings = dict(DEFAULTS)
    try:
        data = json.loads(pathlib.Path(path or config_path()).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return settings
    section = data.get("analysis") if isinstance(data, dict) else None
    if isinstance(section, dict):
        for key in DEFAULTS:
            if key in section and _valid(key, section[key]):
                settings[key] = section[key]
    return settings


def _valid(key, value):
    """잘못된 형식의 값은 버리고 기본값을 쓴다. 문자열 하나가 글자 단위 패턴으로 풀려 모든 파일이 제외되는 일을 막는다."""
    if key in ("summary_globs", "full_globs", "knowledge_dirs"):
        return isinstance(value, list) and all(isinstance(v, str) and v.strip() for v in value)
    if key in ("max_diff_chars", "per_file_chars", "timeout_seconds", "retention_days"):
        return isinstance(value, int) and not isinstance(value, bool) and value > 0
    if key in ("post_comments", "mention_requester", "notify_with_new_comment", "upload_report"):
        return isinstance(value, bool)
    return True
