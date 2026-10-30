"""``ClaudeCliBackend``: exact argv and env of PLAN amendment R1 (no real process)."""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from job_search_agent.judge.backend import (
    WITHHELD_STDERR,
    ClaudeCliBackend,
    UnavailableBackend,
    sanitize_stderr,
)
from job_search_agent.models import BackendErrorKind, CompletedCommand
from tests.fakes import FakeRunner, FixedClock
from tests.judge.doubles import MemoryWriter

RESOLVED = "/opt/fake/bin/claude"
MODEL = "claude-sonnet-5-5"

EXPECTED_ARGV_TAIL = (
    "-p",
    "--no-session-persistence",
    "--tools",
    "",
    "--disallowedTools",
    "mcp__*",
    "--strict-mcp-config",
    "--setting-sources",
    "project",
    "--safe-mode",
    "--output-format",
    "json",
    "--model",
    MODEL,
)

PARENT_ENV = {
    "PATH": "/usr/bin:/bin",
    "HOME": "/home/tester",
    "ANTHROPIC_API_KEY": "sk-ant-test-0000000000000000",
    "ANTHROPIC_AUTH_TOKEN": "tok",
    "ANTHROPIC_BASE_URL": "https://proxy.invalid",
    "CLAUDE_CODE_USE_BEDROCK": "1",
    "CLAUDE_CODE_USE_VERTEX": "1",
    "CLAUDE_CODE_DISABLE_CLAUDE_MDS": "0",
}


def _envelope(**overrides: Any) -> str:
    envelope: dict[str, Any] = {
        "type": "result",
        "subtype": "success",
        "is_error": False,
        "result": '{"label": "RELEVANT"}',
        "session_id": "sess-1",
        "total_cost_usd": 0.0123,
        "modelUsage": {MODEL: {"inputTokens": 10}},
    }
    envelope.update(overrides)
    return json.dumps(envelope)


def _done(
    stdout: str = "",
    *,
    returncode: int | None = 0,
    stderr: str = "",
    timed_out: bool = False,
) -> CompletedCommand:
    return CompletedCommand(
        argv=(),
        returncode=returncode,
        stdout=stdout,
        stderr=stderr,
        timed_out=timed_out,
        duration_ms=42,
    )


def _backend(
    runner: Any, tmp_path: Path, *, which: Any = None, home: str = "/home/tester"
) -> tuple[ClaudeCliBackend, MemoryWriter]:
    writer = MemoryWriter(tmp_path)
    counter = iter(range(1000))
    backend = ClaudeCliBackend(
        executable="claude",
        model_id=MODEL,
        timeout_s=180.0,
        runner=runner,
        make_empty_dir=writer.make_empty_dir,
        clock=FixedClock(datetime(2026, 10, 30, 2, 0, tzinfo=UTC)),
        which=which or (lambda name: RESOLVED if name == "claude" else None),
        base_env=PARENT_ENV,
        new_id=lambda: f"id{next(counter)}",
        home=home,
    )
    return backend, writer


def test_argv_exact(tmp_path: Path) -> None:
    runner = FakeRunner([_done(_envelope())])
    backend, _ = _backend(runner, tmp_path)
    reply = backend.complete("PROMPT")
    assert runner.calls[0].argv == (RESOLVED, *EXPECTED_ARGV_TAIL)
    # The log shows the configured name, never the resolved absolute path.
    assert reply.argv == ("claude", *EXPECTED_ARGV_TAIL)
    assert backend.display_argv == ("claude", *EXPECTED_ARGV_TAIL)
    assert runner.calls[0].timeout_s == 180.0


def test_prompt_on_stdin_not_argv(tmp_path: Path) -> None:
    runner = FakeRunner([_done(_envelope())])
    backend, _ = _backend(runner, tmp_path)
    backend.complete("SECRET-PROMPT-TEXT")
    call = runner.calls[0]
    assert call.stdin == "SECRET-PROMPT-TEXT"
    assert all("SECRET-PROMPT-TEXT" not in arg for arg in call.argv)


class _InspectingRunner:
    """Checks, during the call, that the cwd exists, is empty and under data/tmp."""

    def __init__(self, root: Path, stdout: str) -> None:
        self.root = root
        self.stdout = stdout
        self.cwds: list[Path] = []

    def run(
        self,
        argv: Sequence[str],
        *,
        cwd: Path,
        env: Mapping[str, str],
        stdin: str,
        timeout_s: float,
    ) -> CompletedCommand:
        assert cwd.is_dir()
        assert list(cwd.iterdir()) == []
        assert cwd.parent == self.root / "tmp"
        assert cwd.name.startswith("claude-")
        self.cwds.append(cwd)
        return _done(self.stdout)


def test_fresh_empty_cwd_under_data_tmp_removed_after(tmp_path: Path) -> None:
    runner = _InspectingRunner(tmp_path, _envelope())
    backend, writer = _backend(runner, tmp_path)
    backend.complete("a")
    backend.complete("b")
    assert len(set(runner.cwds)) == 2
    assert writer.made_dirs == ["tmp/claude-id0", "tmp/claude-id1"]
    for cwd in runner.cwds:
        assert not cwd.exists()


def test_cwd_removed_even_when_spawn_fails(tmp_path: Path) -> None:
    runner = FakeRunner([FileNotFoundError("claude")])
    backend, _ = _backend(runner, tmp_path)
    reply = backend.complete("a")
    assert reply.error is BackendErrorKind.SPAWN_FAILED
    assert not runner.calls[0].cwd.exists()


def test_env_strips_api_keys(tmp_path: Path) -> None:
    runner = FakeRunner([_done(_envelope())])
    backend, _ = _backend(runner, tmp_path)
    backend.complete("a")
    env = runner.calls[0].env
    for name in (
        "ANTHROPIC_API_KEY",
        "ANTHROPIC_AUTH_TOKEN",
        "ANTHROPIC_BASE_URL",
        "CLAUDE_CODE_USE_BEDROCK",
        "CLAUDE_CODE_USE_VERTEX",
    ):
        assert name not in env
    assert env["CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC"] == "1"
    assert env["CLAUDE_CODE_DISABLE_CLAUDE_MDS"] == "1"
    assert env["ENABLE_CLAUDEAI_MCP_SERVERS"] == "false"
    assert env["PATH"] == "/usr/bin:/bin" and env["HOME"] == "/home/tester"
    assert "sk-ant-test" not in json.dumps(dict(env))
    assert PARENT_ENV["ANTHROPIC_API_KEY"].startswith("sk-ant")  # parent untouched


def test_not_on_path_unavailable(tmp_path: Path) -> None:
    runner = FakeRunner()
    backend, _ = _backend(runner, tmp_path, which=lambda name: None)
    availability = backend.availability()
    assert not availability.available
    assert availability.reason == "cli_not_found"
    assert runner.calls == []


def test_availability_records_version_once(tmp_path: Path) -> None:
    runner = FakeRunner([_done("2.1.312 (Claude Code)\n")])
    backend, _ = _backend(runner, tmp_path)
    assert backend.availability().version == "2.1.312 (Claude Code)"
    assert backend.availability().available
    assert len(runner.calls) == 1
    assert runner.calls[0].argv == (RESOLVED, "--version")
    assert "ANTHROPIC_API_KEY" not in runner.calls[0].env


def test_envelope_parsed(tmp_path: Path) -> None:
    runner = FakeRunner([_done(_envelope(), stderr="note")])
    backend, _ = _backend(runner, tmp_path)
    reply = backend.complete("a")
    assert reply.ok and reply.error is None
    assert reply.result_text == '{"label": "RELEVANT"}'
    assert reply.session_id == "sess-1"
    assert reply.model_served == (MODEL,)
    assert reply.total_cost_usd == pytest.approx(0.0123)
    assert reply.raw_stdout == _envelope()
    assert reply.exit_code == 0 and reply.duration_ms == 42
    assert reply.stderr == "note"


def test_envelope_not_json_is_ERROR(tmp_path: Path) -> None:  # noqa: N802
    runner = FakeRunner([_done("not json"), _done("[1, 2]")])
    backend, _ = _backend(runner, tmp_path)
    for _ in range(2):
        reply = backend.complete("a")
        assert reply.error is BackendErrorKind.ENVELOPE_NOT_JSON
        assert not reply.ok


def test_envelope_shape_and_is_error(tmp_path: Path) -> None:
    runner = FakeRunner(
        [
            _done(_envelope(result=None)),
            _done(_envelope(is_error=True, result="API Error")),
            _done(_envelope(is_error=True), returncode=1),
            _done("", returncode=2),
            _done("", returncode=None, timed_out=True),
        ]
    )
    backend, _ = _backend(runner, tmp_path)
    kinds = [backend.complete("a").error for _ in range(5)]
    assert kinds == [
        BackendErrorKind.ENVELOPE_SHAPE,
        BackendErrorKind.IS_ERROR,
        BackendErrorKind.IS_ERROR,
        BackendErrorKind.NONZERO_EXIT,
        BackendErrorKind.TIMEOUT,
    ]


def test_no_bare_flag(tmp_path: Path) -> None:
    runner = FakeRunner([_done(_envelope())])
    backend, _ = _backend(runner, tmp_path)
    backend.complete("a")
    argv = runner.calls[0].argv
    for flag in (
        "--bare",
        "--dangerously-skip-permissions",
        "--json-schema",
        "--setting-sources=",
    ):
        assert flag not in argv
    assert argv[argv.index("--setting-sources") + 1] == "project"


def test_stderr_with_credential_pattern_withheld(tmp_path: Path) -> None:
    runner = FakeRunner(
        [
            _done(_envelope(), stderr="auth failed for sk-ant-api03-abcdef"),
            _done(_envelope(), stderr="Bearer abc.def"),
            _done(_envelope(), stderr="warning in /home/tester/.claude/x"),
        ]
    )
    backend, _ = _backend(runner, tmp_path)
    assert backend.complete("a").stderr == WITHHELD_STDERR
    assert backend.complete("a").stderr == WITHHELD_STDERR
    assert backend.complete("a").stderr == "warning in ~/.claude/x"


def test_sanitize_stderr_plain_text_kept() -> None:
    assert sanitize_stderr("rate limited", home="/h") == "rate limited"


def test_unavailable_backend() -> None:
    backend = UnavailableBackend()
    assert backend.availability().reason == "backend_none"
    with pytest.raises(RuntimeError):
        backend.complete("x")
