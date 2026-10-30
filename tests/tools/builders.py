"""Builders shared by the WS1 tests: the fixture résumé and constructed postings.

``fixture_resume`` checks the committed fixture's bytes against the independently
pinned digest in ``tests.conftest`` before wrapping them, so the rule tests do not
depend on WS2's résumé gate (``resume.load_verified_resume``) being merged. It is a
test-only stand-in; production code obtains a ``VerifiedResume`` only from that gate.
"""

from __future__ import annotations

import hashlib
import json
from functools import cache
from typing import Any

from job_search_agent.models import ParsedBoard, Posting, VerifiedResume
from job_search_agent.providers.greenhouse import GreenhouseProvider
from tests.conftest import (
    HANDCHECK_RAW_REL,
    PINNED_RESUME_SHA256,
    REPO_ROOT,
    RESUME_FIXTURE_REL,
)


@cache
def _fixture_bytes() -> bytes:
    body = (REPO_ROOT / RESUME_FIXTURE_REL).read_bytes()
    digest = hashlib.sha256(body).hexdigest()
    if digest != PINNED_RESUME_SHA256:
        raise AssertionError("fixture bytes differ from the pinned digest")
    return body


def fixture_resume_data() -> dict[str, Any]:
    """Returns a fresh parsed copy of the committed fixture."""
    data: dict[str, Any] = json.loads(_fixture_bytes())
    return data


def fixture_resume(data: dict[str, Any] | None = None) -> VerifiedResume:
    """Wraps the fixture (or a mutated copy of it) as a ``VerifiedResume``.

    Args:
        data: A mutated copy of the fixture for tests that change one field; the
            committed fixture when omitted.

    Returns:
        The wrapped résumé.
    """
    return VerifiedResume(
        fixture_resume_data() if data is None else data,
        sha256=PINNED_RESUME_SHA256,
        source_path=RESUME_FIXTURE_REL,
    )


def job(**fields: Any) -> dict[str, Any]:
    """A constructed Greenhouse job object; keyword arguments override defaults.

    Defaults: ``Software Engineer`` in ``Seattle, WA`` with empty content and one
    ``Engineering`` department. Delete keys from the result when a field must be
    absent.
    """
    base: dict[str, Any] = {
        "id": 1,
        "title": "Software Engineer",
        "location": {"name": "Seattle, WA"},
        "updated_at": None,
        "content": "",
        "departments": [{"name": "Engineering"}],
    }
    base.update(fields)
    return base


def posting(**fields: Any) -> Posting:
    """A constructed posting, normalised through the real Greenhouse parser.

    Args:
        **fields: Overrides for ``job``. ``content`` is plain text or HTML; it is
            stored as given (not escaped).

    Returns:
        The single parsed posting.
    """
    return posting_from_job(job(**fields))


def posting_from_job(raw_job: dict[str, Any]) -> Posting:
    """Normalises one job object through the real Greenhouse parser."""
    body = json.dumps({"jobs": [raw_job], "meta": {"total": 1}}).encode()
    (only,) = GreenhouseProvider().parse(body).postings
    return only


@cache
def handcheck_board() -> ParsedBoard:
    """The committed §13 raw response, parsed once per test session."""
    return GreenhouseProvider().parse((REPO_ROOT / HANDCHECK_RAW_REL).read_bytes())


def handcheck_posting(posting_id: str) -> Posting:
    """One posting of the committed §13 raw response, by ID."""
    (found,) = [p for p in handcheck_board().postings if p.posting_id == posting_id]
    return found
