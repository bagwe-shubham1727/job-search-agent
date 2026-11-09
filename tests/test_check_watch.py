"""The independent check, run on committed loop runs (real evidence)."""

from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType

from tests.conftest import REPO_ROOT

LIVE_RUN_1 = REPO_ROOT / "data/watch/loops/2026-11-09T08-14-22Z"
WRONG_BOARD_RUN = REPO_ROOT / "data/watch/loops/2026-11-09T08-16-16Z"
AFTER_PATCH_RUN = REPO_ROOT / "data/watch/loops/2026-11-09T08-23-46Z"
EXPECTATIONS = REPO_ROOT / "checks/expectations.toml"


def _checker() -> ModuleType:
    spec = importlib.util.spec_from_file_location(
        "check_watch", REPO_ROOT / "checks/check_watch.py"
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _failures(loop_dir: Path) -> set[tuple[str, str]]:
    rows = _checker().check_loop(loop_dir, EXPECTATIONS)
    return {(board, check) for board, check, passed, _ in rows if not passed}


def test_live_run_1_passes_every_check() -> None:
    assert _failures(LIVE_RUN_1) == set()


def test_wrong_board_run_is_caught() -> None:
    assert _failures(WRONG_BOARD_RUN) == {
        ("(loop)", "FINISHED only if every board is OK and checks out"),
        ("greenhouse/ramp", "careers page uses this system"),
        ("greenhouse/ramp", "at least the expected floor"),
    }


def test_after_patch_run_agrees_with_the_check() -> None:
    assert _failures(AFTER_PATCH_RUN) == set()


def test_checker_imports_nothing_from_the_agent() -> None:
    source = (REPO_ROOT / "checks/check_watch.py").read_text()
    assert "job_search_agent" not in source
