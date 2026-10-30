"""Smoke tests for the WS0 CLI skeleton.

WS3 replaces the stubs; delete or rewrite the stub tests here when it does.
"""

from __future__ import annotations

import importlib

import pytest

from job_search_agent import cli


def test_help_lists_every_subcommand(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as exit_info:
        cli.main(["--help"])
    assert exit_info.value.code == 0
    out = capsys.readouterr().out
    for command in (
        "run",
        "doctor",
        "pending",
        "rule",
        "verify-evidence",
        "audit-privacy",
    ):
        assert command in out


@pytest.mark.parametrize(
    ("argv", "owner"),
    [
        (["run"], "WS3"),
        (["run", "--model-backend", "none"], "WS3"),
        (["doctor", "--probe-model"], "WS3"),
        (["pending", "list"], "WS3"),
        (["pending", "drop", "123", "--reason", "gone"], "WS3"),
        (["rule", "--raw", "x.json", "--id", "8249901"], "WS1"),
        (["verify-evidence"], "WS3"),
        (["audit-privacy", "data/"], "WS2"),
    ],
)
def test_stubs_report_not_implemented(
    argv: list[str], owner: str, capsys: pytest.CaptureFixture[str]
) -> None:
    assert cli.main(argv) == cli.NOT_IMPLEMENTED_EXIT
    assert f"not implemented yet ({owner})" in capsys.readouterr().err


def test_missing_experiments_module_does_not_break_cli(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def missing(name: str) -> None:
        raise ModuleNotFoundError(f"No module named {name!r}", name=name)

    monkeypatch.setattr(importlib, "import_module", missing)
    parser = cli.build_parser()
    assert parser.parse_args(["doctor"]).command == "doctor"


def test_broken_experiments_import_is_not_hidden(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def broken(_name: str) -> None:
        raise ModuleNotFoundError("No module named 'numpy'", name="numpy")

    monkeypatch.setattr(importlib, "import_module", broken)
    with pytest.raises(ModuleNotFoundError):
        cli.build_parser()
