"""Repository hygiene: ignore rules, no real résumé, no absolute paths (CONTRACT §12).

These tests ask git about the committed tree, so they are marked ``subprocess``.

Scope of the absolute-path check: every tracked file under ``data/`` (all generated
by the agent) and every tracked file under ``docs/`` except the hand-written planning
notes in ``PROSE_EXCLUSIONS``. Those notes legitimately name the author's checkout
path in prose (e.g. PLAN.md's "Critical Files" list); they are inputs to the build,
not artifacts the agent produced.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path, PurePosixPath

import pytest

from tests.conftest import REPO_ROOT, RESUME_FIXTURE_REL

pytestmark = pytest.mark.subprocess

PROSE_EXCLUSIONS = frozenset({"docs/PLAN.md"})
"""Hand-written planning docs exempt from the absolute-path scan (see module doc)."""

ABSOLUTE_PATH_MARKERS = ("/Users/", "/home/", "/private/var/folders/")


def _git(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(  # noqa: S603 - fixed argv, no shell
        ["git", *args],  # noqa: S607 - git from PATH is the point
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )


def _tracked(*pathspecs: str) -> list[str]:
    done = _git("ls-files", "-z", "--", *pathspecs)
    assert done.returncode == 0, done.stderr
    return [path for path in done.stdout.split("\0") if path]


def _ignored(path: str) -> bool:
    # --no-index tests the rules themselves, even for paths that are tracked.
    done = _git("check-ignore", "--no-index", "-q", path)
    assert done.returncode in (0, 1), done.stderr
    return done.returncode == 0


@pytest.mark.parametrize(
    "path",
    [
        "private/x",
        "private/real-resume.pdf",
        "resume.json",
        "me.resume.json",
        "persona/me.resume.json",
        "data/tmp/judge-1/x",
        ".env",
    ],
)
def test_gitignore_rules_hit(path: str) -> None:
    assert _ignored(path)


@pytest.mark.parametrize(
    "path", [RESUME_FIXTURE_REL, "data/live/state.json", "docs/RUNS.md"]
)
def test_gitignore_rules_miss(path: str) -> None:
    assert not _ignored(path)


def test_no_real_resume_tracked() -> None:
    tracked = _tracked()
    assert not [p for p in tracked if p.startswith("private/")]
    names = {p: PurePosixPath(p).name.lower() for p in tracked}
    resume_like = [
        p
        for p, name in names.items()
        if "resume" in name and PurePosixPath(name).suffix in {".json", ".pdf", ".docx"}
    ]
    assert resume_like == [RESUME_FIXTURE_REL]
    for path in resume_like:
        assert path.endswith(".resume.example.json")
        doc = json.loads((REPO_ROOT / path).read_bytes())
        assert doc["fictional"] is True
        assert doc["personal"]["email"].endswith("@example.com")


def test_no_absolute_paths_in_committed_artifacts() -> None:
    offenders = []
    for path in _tracked("data", "docs"):
        if path in PROSE_EXCLUSIONS:
            continue
        file = REPO_ROOT / path
        if file.is_symlink() or not file.is_file():
            continue
        text = Path(file).read_bytes().decode("utf-8", errors="replace")
        for marker in ABSOLUTE_PATH_MARKERS:
            if marker in text:
                line = text[: text.index(marker)].count("\n") + 1
                offenders.append(f"{path}:{line} contains {marker!r}")
    assert offenders == []


def test_prose_exclusions_are_tracked_docs() -> None:
    """Keeps the exemption list honest: each entry must exist and be under docs/."""
    tracked = set(_tracked("docs"))
    for path in PROSE_EXCLUSIONS:
        assert path in tracked
        assert path.startswith("docs/")
