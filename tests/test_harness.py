"""Tests for the test harness itself: guards, options and fakes (WS0)."""

from __future__ import annotations

import socket
import subprocess
import sys
from pathlib import Path
from typing import Any

import httpx
import pytest

from job_search_agent.models import BackendErrorKind, CompletedCommand
from tests.conftest import (
    RULE_IMPLS,
    NetworkBlockedError,
    RawHandcheck,
    SubprocessBlockedError,
)
from tests.fakes import FakeBackend, FakeGit, FakeRunner, FixedClock, Reply


def test_network_is_blocked() -> None:
    with pytest.raises(NetworkBlockedError):
        socket.create_connection(("example.com", 443))
    with socket.socket() as sock, pytest.raises(NetworkBlockedError):
        sock.connect(("127.0.0.1", 9))
    with pytest.raises(NetworkBlockedError):
        socket.getaddrinfo("example.com", 443)


def test_subprocess_is_blocked() -> None:
    with pytest.raises(SubprocessBlockedError):
        subprocess.run([sys.executable, "-c", "pass"], check=False)  # noqa: S603


@pytest.mark.subprocess
def test_subprocess_marker_lifts_guard() -> None:
    done = subprocess.run(  # noqa: S603
        [sys.executable, "-c", "print('ok')"],
        check=True,
        capture_output=True,
        text=True,
    )
    assert done.stdout.strip() == "ok"


@pytest.mark.live
def test_live_tests_run_only_with_flag(request: pytest.FixtureRequest) -> None:
    assert request.config.getoption("--live") is True


def test_rule_impl_option(rule_impl: str, request: pytest.FixtureRequest) -> None:
    assert rule_impl in RULE_IMPLS
    assert rule_impl == request.config.getoption("--rule-impl")


def test_raw_handcheck_fixture(raw_handcheck: RawHandcheck) -> None:
    assert raw_handcheck.meta["bytes"] == len(raw_handcheck.body)
    assert isinstance(raw_handcheck.data["jobs"], list)


def test_fixed_clock_fixture(fixed_clock: FixedClock) -> None:
    first, second = fixed_clock.now_utc(), fixed_clock.now_utc()
    assert (second - first).total_seconds() == 1


def test_mock_transport_records_and_routes(mock_transport: Any) -> None:
    url = "https://boards-api.greenhouse.io/v1/boards/stripe/jobs?content=true"
    transport = mock_transport({url: Reply(200, b'{"jobs": []}')})
    with httpx.Client(transport=transport) as client:
        assert client.get(url).json() == {"jobs": []}
        assert client.get(url).status_code == 200  # fresh response each time
        with pytest.raises(AssertionError, match="unexpected request"):
            client.get("https://elsewhere.example/")
    assert [str(r.url) for r in transport.requests[:2]] == [url, url]


def test_fake_backend_script() -> None:
    backend = FakeBackend(['{"label": "RELEVANT"}', BackendErrorKind.TIMEOUT])
    assert backend.availability().available
    first = backend.complete("prompt")
    assert first.ok
    assert first.result_text == '{"label": "RELEVANT"}'
    second = backend.complete("prompt")
    assert not second.ok
    assert second.error is BackendErrorKind.TIMEOUT
    assert backend.calls == 2
    with pytest.raises(AssertionError, match="exhausted"):
        backend.complete("prompt")


def test_fake_backend_unavailable(fake_backend: FakeBackend) -> None:
    unavailable = FakeBackend(available=False)
    assert unavailable.availability().reason == "backend_none"
    with pytest.raises(AssertionError):
        unavailable.complete("prompt")
    assert fake_backend.calls == 0


def test_fake_runner_records_calls(tmp_path: Path) -> None:
    runner = FakeRunner(
        [CompletedCommand((), 0, "out", "", timed_out=False, duration_ms=3)]
    )
    result = runner.run(
        ["claude", "-p"], cwd=tmp_path, env={"A": "1"}, stdin="hi", timeout_s=1.0
    )
    assert result.argv == ("claude", "-p")
    assert result.stdout == "out"
    assert runner.calls[0].stdin == "hi"
    assert runner.calls[0].env == {"A": "1"}


def test_fake_git(fake_git: FakeGit) -> None:
    fake_git.clean_tracked.add("experiments/prompt/SEAL.json")
    assert fake_git.is_tracked_and_clean(Path("experiments/prompt/SEAL.json"))
    assert not fake_git.is_tracked_and_clean(Path("other"))
    assert len(fake_git.head()) == 40
