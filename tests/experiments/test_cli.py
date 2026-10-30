"""``jsa exp`` registration and handler behaviour (no real wiring)."""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any

import pytest

from job_search_agent.cli import build_parser
from job_search_agent.experiments._io import EXPERIMENT_REFUSED_EXIT
from job_search_agent.experiments.cli import register
from tests.experiments.helpers import make_repo


class _FakeWiring:
    def __init__(self, context: Any) -> None:
        self.context = context


def _parser(wiring: Any) -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="jsa")
    sub = parser.add_subparsers(dest="command", required=True)
    register(sub, wiring=lambda _args: wiring)
    return parser


@pytest.mark.parametrize(
    "argv",
    [
        ["exp", "sampling", "run", "--n", "4"],
        ["exp", "sampling", "table"],
        ["exp", "prompt", "select"],
        ["exp", "prompt", "seal"],
        ["exp", "prompt", "run", "--prompt", "v1", "--set", "dev"],
        ["exp", "prompt", "run", "--prompt", "v2", "--set", "heldout"],
        ["exp", "prompt", "freeze"],
        ["exp", "prompt", "score"],
        ["exp", "surfaces", "prepare"],
        ["exp", "surfaces", "run", "c", "--dry-run"],
        ["exp", "surfaces", "capture"],
    ],
)
def test_main_parser_registers_exp_commands(argv: list[str]) -> None:
    args = build_parser().parse_args(argv)
    assert callable(args.handler)


def test_bad_prompt_choice_rejected() -> None:
    with pytest.raises(SystemExit):
        build_parser().parse_args(
            ["exp", "prompt", "run", "--prompt", "v3", "--set", "dev"]
        )


def test_refused_gate_returns_distinct_exit(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    repo = make_repo(tmp_path)
    parser = _parser(_FakeWiring(repo.ctx))
    args = parser.parse_args(["exp", "prompt", "seal"])
    assert args.handler(args) == EXPERIMENT_REFUSED_EXIT
    assert "refused: no selection yet" in capsys.readouterr().err


def test_sampling_table_success_prints_summary(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    repo = make_repo(tmp_path)
    parser = _parser(_FakeWiring(repo.ctx))
    args = parser.parse_args(["exp", "sampling", "table"])
    assert args.handler(args) == EXPERIMENT_REFUSED_EXIT  # no manifest yet
    assert "no sampling manifest" in capsys.readouterr().err
