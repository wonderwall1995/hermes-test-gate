"""claude -p 실행기. 도구 없이, 사용자 설정을 읽지 않고, 구독 로그인으로 실행한다."""

import json
import subprocess
import tempfile


EFFORT_LEVELS = ("low", "medium", "high", "xhigh", "max")


class RunnerError(Exception):
    pass


class ClaudeRunner:
    def __init__(self, binary="claude", model=None, timeout=300, effort=None):
        if effort is not None and effort not in EFFORT_LEVELS:
            raise RunnerError(f"effort 값이 잘못되었다: {effort!r} (허용: {', '.join(EFFORT_LEVELS)})")
        self.binary = binary
        self.model = model
        self.timeout = timeout
        self.effort = effort

    def command(self, system_prompt, schema):
        cmd = [
            self.binary, "-p",
            "--tools", "",
            "--strict-mcp-config",
            "--disable-slash-commands",
            "--no-session-persistence",
            "--setting-sources", "",
            "--output-format", "json",
            "--json-schema", json.dumps(schema, ensure_ascii=False),
            "--system-prompt", system_prompt,
        ]
        if self.model:
            cmd += ["--model", self.model]
        if self.effort:
            cmd += ["--effort", self.effort]
        return cmd

    def run(self, system_prompt, user_prompt, schema):
        """(구조화된 출력, 메타 정보)를 반환한다."""
        # 빈 임시 폴더에서 실행한다. 읽을 파일이 없다.
        with tempfile.TemporaryDirectory(prefix="testgate-") as workdir:
            try:
                proc = subprocess.run(
                    self.command(system_prompt, schema),
                    input=user_prompt, capture_output=True, text=True, encoding="utf-8",
                    errors="replace", timeout=self.timeout, cwd=workdir,
                )
            except subprocess.TimeoutExpired:
                raise RunnerError(f"Claude 실행이 {self.timeout}초를 넘었다")
            except FileNotFoundError:
                raise RunnerError(f"Claude 실행 파일을 찾을 수 없다: {self.binary}")
        if proc.returncode != 0:
            raise RunnerError(f"Claude 종료 코드 {proc.returncode}: {proc.stderr.strip()[:300]}")
        try:
            envelope = json.loads(proc.stdout)
        except json.JSONDecodeError:
            raise RunnerError("Claude 출력이 JSON이 아니다")
        if not isinstance(envelope, dict) or envelope.get("is_error"):
            raise RunnerError("Claude가 오류를 반환했다")
        output = envelope.get("structured_output")
        if not isinstance(output, dict):
            raise RunnerError("구조화된 출력이 없다")
        meta = {
            "cost_usd": envelope.get("total_cost_usd"),
            "duration_ms": envelope.get("duration_ms"),
            "models": sorted((envelope.get("modelUsage") or {}).keys()),
        }
        return output, meta
