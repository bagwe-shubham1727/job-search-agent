"""``jsa`` command-line entry point (skeleton from WS0; WS3 owns it afterwards).

Each subcommand is registered with its documented arguments (PLAN §1.5) and a
handler. Until a workstream implements a handler, the stub prints which workstream
owns it and exits with ``NOT_IMPLEMENTED_EXIT``. The ``exp`` command group is added
by ``job_search_agent.experiments.cli.register`` when that module exists (WS4); its
absence does not break the CLI.
"""

from __future__ import annotations

import argparse
import importlib
import sys
from collections.abc import Callable, Sequence
from pathlib import Path

from job_search_agent.config import DEFAULT_CONFIG_PATH
from job_search_agent.errors import AgentError

Handler = Callable[[argparse.Namespace], int]
"""A subcommand handler: receives parsed arguments, returns the exit code."""

type Subparsers = argparse._SubParsersAction[argparse.ArgumentParser]
"""The object returned by ``add_subparsers``; registrars add commands to it."""

NOT_IMPLEMENTED_EXIT = 70
"""Exit status of a stub (BSD ``EX_SOFTWARE``); distinct from every run exit code."""

_EXPERIMENTS_MODULE = "job_search_agent.experiments.cli"
_EXPERIMENTS_ABSENT = frozenset({"job_search_agent.experiments", _EXPERIMENTS_MODULE})


def _not_implemented(command: str, owner: str) -> Handler:
    """Builds a stub handler for a subcommand that is not implemented yet.

    Args:
        command: The subcommand name, for the message.
        owner: The workstream that will implement it, e.g. ``"WS3"``.

    Returns:
        A handler that prints the message to stderr and returns
        ``NOT_IMPLEMENTED_EXIT``.
    """

    def handler(_args: argparse.Namespace) -> int:
        print(f"jsa {command}: not implemented yet ({owner})", file=sys.stderr)
        return NOT_IMPLEMENTED_EXIT

    return handler


def _add_run(sub: Subparsers) -> None:
    """Registers ``jsa run``."""
    parser = sub.add_parser("run", help="fetch the board once, apply the rule, judge")
    parser.add_argument(
        "--replay",
        type=Path,
        metavar="RAW_JSON",
        help="replay a saved raw response instead of fetching (seeded run)",
    )
    parser.add_argument(
        "--model-backend",
        choices=("claude-cli", "none"),
        help="override [model].backend; 'none' marks every judgment UNAVAILABLE",
    )
    parser.set_defaults(handler=_not_implemented("run", "WS3"))


def _add_doctor(sub: Subparsers) -> None:
    """Registers ``jsa doctor``."""
    parser = sub.add_parser("doctor", help="offline environment and fixture checks")
    parser.add_argument(
        "--probe-model",
        action="store_true",
        help="make one tiny real model call and record the facts in data/doctor/",
    )
    parser.set_defaults(handler=_not_implemented("doctor", "WS3"))


def _add_pending(sub: Subparsers) -> None:
    """Registers ``jsa pending list|drop``."""
    parser = sub.add_parser("pending", help="inspect or drop pending judgments")
    actions = parser.add_subparsers(dest="pending_action", required=True)
    list_parser = actions.add_parser("list", help="list pending judgments")
    list_parser.add_argument("--data", choices=("live", "seeded"), default="live")
    list_parser.set_defaults(handler=_not_implemented("pending list", "WS3"))
    drop_parser = actions.add_parser("drop", help="stop retrying one posting")
    drop_parser.add_argument("posting_id")
    drop_parser.add_argument("--reason", required=True, help="documented reason")
    drop_parser.add_argument("--data", choices=("live", "seeded"), default="live")
    drop_parser.set_defaults(handler=_not_implemented("pending drop", "WS3"))


def _add_rule(sub: Subparsers) -> None:
    """Registers ``jsa rule``."""
    parser = sub.add_parser("rule", help="print the rule record for one posting")
    parser.add_argument("--raw", type=Path, required=True, metavar="RAW_JSON")
    parser.add_argument("--id", dest="posting_id", required=True)
    parser.set_defaults(handler=_not_implemented("rule", "WS1"))


def _add_verify_evidence(
    sub: Subparsers,
) -> None:
    """Registers ``jsa verify-evidence``."""
    parser = sub.add_parser(
        "verify-evidence", help="recompute every saved raw sha256 against its meta"
    )
    parser.set_defaults(handler=_not_implemented("verify-evidence", "WS3"))


def _add_audit_privacy(
    sub: Subparsers,
) -> None:
    """Registers ``jsa audit-privacy``."""
    parser = sub.add_parser(
        "audit-privacy", help="scan outputs for résumé values, credentials, abs paths"
    )
    parser.add_argument("path", type=Path, nargs="?", default=Path("data"))
    parser.set_defaults(handler=_not_implemented("audit-privacy", "WS2"))


_REGISTRY: tuple[Callable[[Subparsers], None], ...] = (
    _add_run,
    _add_doctor,
    _add_pending,
    _add_rule,
    _add_verify_evidence,
    _add_audit_privacy,
)


def _register_experiments(
    sub: Subparsers,
) -> None:
    """Adds ``jsa exp ...`` if the experiments package is installed.

    Args:
        sub: The top-level subparsers object.

    Raises:
        ModuleNotFoundError: If the experiments module exists but one of *its* imports
            is missing (a real bug, not an absent workstream).
    """
    try:
        module = importlib.import_module(_EXPERIMENTS_MODULE)
    except ModuleNotFoundError as exc:
        if exc.name in _EXPERIMENTS_ABSENT:
            return
        raise
    module.register(sub)


def build_parser() -> argparse.ArgumentParser:
    """Builds the full ``jsa`` argument parser.

    Returns:
        The parser; every subcommand sets a ``handler`` default.
    """
    parser = argparse.ArgumentParser(
        prog="jsa",
        description=(
            "Job-Search Agent: discovery only. Watches one public job board, applies a "
            "deterministic rule and records a separate Claude opinion."
        ),
    )
    parser.add_argument(
        "--config",
        type=Path,
        default=DEFAULT_CONFIG_PATH,
        help=f"configuration file (default: {DEFAULT_CONFIG_PATH})",
    )
    sub = parser.add_subparsers(dest="command", required=True, metavar="COMMAND")
    for register in _REGISTRY:
        register(sub)
    _register_experiments(sub)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Runs ``jsa``.

    Args:
        argv: Arguments without the program name; defaults to ``sys.argv[1:]``.

    Returns:
        The process exit code. Deliberate failures (``AgentError``) print their
        content-free message and return their own exit code.
    """
    args = build_parser().parse_args(argv)
    handler: Handler = args.handler
    try:
        return handler(args)
    except AgentError as exc:
        print(f"jsa: {exc}", file=sys.stderr)
        return int(exc.exit_code)


if __name__ == "__main__":
    sys.exit(main())
