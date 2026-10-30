"""Local test doubles for WS4 tests (stand-ins for WS1/WS2 modules not in this tree).

* ``simple_clean`` stands in for WS1's ``text.clean_html``: unescape, strip tags
  (replaced by a space), unescape again, collapse whitespace.
* ``posting_from_raw`` stands in for WS1's Greenhouse parser for one job object.
* ``make_resume`` builds a ``VerifiedResume`` from the committed fixture directly,
  standing in for WS2's gate (the gate itself is tested by WS2).
* ``MemoryWriter`` stands in for WS2's ``OutputRoot`` (atomic writes, empty dirs).
"""

from __future__ import annotations

import html
import json
import re
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from job_search_agent.models import Posting, VerifiedResume
from job_search_agent.resume import load_verified_resume

REPO_ROOT = Path(__file__).resolve().parents[2]
RESUME_REL = "persona/kiran-joshi.resume.example.json"
PINNED = "562a9d607213564c5291520f375ba69a7d407894c5803a995bad5b2d8f810532"
RAW_REL = "evidence/handcheck/stripe-jobs-2026-10-29T22-41-31Z.json"
HANDCHECK = {
    "8249901": 566,
    "7543868": 575,
    "8175099": 556,
    "8127182": 604,
    "8234357": 273,
}

_TAG = re.compile(r"<[^>]*>")
_SPACE = re.compile(r"\s+")


def simple_clean(raw: str) -> str:
    text = html.unescape(raw)
    text = _TAG.sub(" ", text)
    text = html.unescape(text)
    return _SPACE.sub(" ", text.replace("\xa0", " ")).strip()


def make_resume() -> VerifiedResume:
    """The committed fixture, verified through the real résumé gate (pinned digest)."""
    return load_verified_resume(REPO_ROOT / RESUME_REL, PINNED, project_root=REPO_ROOT)


def posting_from_raw(job: Mapping[str, Any], index: int) -> Posting:
    location = job.get("location")
    name = location.get("name") if isinstance(location, Mapping) else None
    departments = job.get("departments") or []
    return Posting(
        posting_id=str(job["id"]),
        index=index,
        raw=job,
        title=str(job.get("title") or ""),
        location_name=name if isinstance(name, str) else None,
        updated_at=job.get("updated_at")
        if isinstance(job.get("updated_at"), str)
        else None,
        content_raw=str(job.get("content") or ""),
        department_names=tuple(
            str(d.get("name") or "") if isinstance(d, Mapping) else ""
            for d in departments
        ),
    )


_RAW_CACHE: dict[str, Any] = {}


def raw_board() -> dict[str, Any]:
    if "board" not in _RAW_CACHE:
        _RAW_CACHE["board"] = json.loads((REPO_ROOT / RAW_REL).read_bytes())
    board: dict[str, Any] = _RAW_CACHE["board"]
    return board


def parse_board(body: bytes) -> Sequence[Posting]:
    data = json.loads(body)
    return tuple(posting_from_raw(job, i) for i, job in enumerate(data["jobs"]))


def handcheck_posting(posting_id: str = "8249901") -> Posting:
    index = HANDCHECK[posting_id]
    return posting_from_raw(raw_board()["jobs"][index], index)


def small_posting(**overrides: Any) -> Posting:
    job: dict[str, Any] = {
        "id": 1234,
        "title": "Software Engineer",
        "location": {"name": "Seattle, WA"},
        "content": "&lt;p&gt;Java and Python on AWS&lt;/p&gt;",
        "departments": [{"name": "Engineering"}],
        "absolute_url": "https://example.invalid/jobs/1234",
        "updated_at": "2026-10-29T10:00:00-04:00",
    }
    job.update(overrides)
    return posting_from_raw(job, 0)


class MemoryWriter:
    """In-memory ``OutputRoot`` double rooted at ``root`` (a tmp dir)."""

    def __init__(self, root: Path) -> None:
        self.root = root
        self.json: dict[str, Any] = {}
        self.bytes: dict[str, bytes] = {}
        self.made_dirs: list[str] = []

    def resolve_for_write(self, rel: str) -> Path:
        assert not rel.startswith("/") and ".." not in rel.split("/")
        return self.root / rel

    def write_json_atomic(self, rel: str, obj: object) -> Path:
        self.json[rel] = json.loads(json.dumps(obj))
        path = self.resolve_for_write(rel)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(obj, sort_keys=True, indent=2) + "\n", "utf-8")
        return path

    def write_bytes_atomic(self, rel: str, data: bytes) -> Path:
        self.bytes[rel] = data
        path = self.resolve_for_write(rel)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        return path

    def make_empty_dir(self, rel: str) -> Path:
        path = self.resolve_for_write(rel)
        path.mkdir(parents=True, exist_ok=False)
        self.made_dirs.append(rel)
        return path


def valid_reply(**overrides: Any) -> dict[str, Any]:
    reply: dict[str, Any] = {
        "label": "RELEVANT",
        "summary": "Title, skills and location line up.",
        "evidence": [
            {
                "resume_path": "$.skills.languages[2]",
                "posting_path": "$.content",
                "reason": "Java appears in the posting.",
            }
        ],
        "uncertainties": ["Sponsorship policy is not stated."],
    }
    reply.update(overrides)
    return reply
