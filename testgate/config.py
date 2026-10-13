"""분석기 설정. testgate.json 의 선택 항목 "analysis" 를 읽는다. 파일이 없어도 기본값으로 동작한다."""

import json
import os
import pathlib

DEFAULTS = {
    "claude_binary": "claude",
    "claude_model": None,
    "claude_effort": None,
    "timeout_seconds": 300,
    "max_diff_chars": 120000,
    "knowledge_dirs": [],
    "github_app_url": "http://127.0.0.1:3200",
    "post_comments": True,
    "route_name": "github-app",
    "hermes_binary": "hermes",
    "retention_days": 30,
}


def config_path():
    explicit = os.environ.get("TESTGATE_CONFIG")
    if explicit:
        return pathlib.Path(explicit)
    home = os.environ.get("HERMES_HOME")
    base = pathlib.Path(home) if home else pathlib.Path.home() / ".hermes"
    return base / "testgate.json"


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
            if key in section:
                settings[key] = section[key]
    return settings
