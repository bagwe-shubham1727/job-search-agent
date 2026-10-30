"""Payloads sent to Claude (PLAN §5.2; CONTRACT §4, §12)."""

from __future__ import annotations

import json

import pytest

from job_search_agent.jsonpath import resolve
from job_search_agent.judge.payload import (
    build_posting_payload,
    build_resume_payload,
    payload_sha256,
)
from tests.judge.doubles import (
    handcheck_posting,
    make_resume,
    simple_clean,
    small_posting,
)


def test_resume_payload_excludes_personal_education_employers_comment_workauth() -> (
    None
):
    payload = build_resume_payload(make_resume())
    assert set(payload) == {"target", "skills", "experience", "projects"}
    for entry in payload["experience"] + payload["projects"]:
        assert set(entry) == {"bullets"}
    original = make_resume().to_dict()
    text = json.dumps(payload)
    forbidden = [
        original["personal"]["name"],
        original["personal"]["email"],
        original["personal"]["phone"],
        original["personal"]["linkedin"],
        original["personal"]["github"],
        original["_comment"],
        *(e["institution"] for e in original["education"]),
        *(e["company"] for e in original["experience"]),
        *(p["name"] for p in original["projects"]),
        *(e["start_date"] for e in original["experience"]),
    ]
    for value in forbidden:
        assert value not in text


def test_resume_payload_preserves_indices() -> None:
    payload = build_resume_payload(make_resume())
    original = make_resume().to_dict()
    paths = [
        "$.skills.backend[4]",
        "$.skills.cloud_devops[0]",
        "$.skills.languages[5]",
        "$.skills.familiar_with_not_shipped[1]",
        "$.target.roles[3]",
        "$.target.excluded[1]",
        "$.experience[1].bullets[0]",
        "$.projects[1].bullets[0]",
    ]
    for path in paths:
        assert resolve(payload, path) == resolve(original, path), path
    assert resolve(payload, "$.skills.backend[4]") == "GraphQL"


def test_resume_payload_rejects_unverified_mapping() -> None:
    with pytest.raises(TypeError):
        build_resume_payload(make_resume().to_dict())  # type: ignore[arg-type]


def test_posting_payload_fields_only() -> None:
    payload = build_posting_payload(handcheck_posting("8249901"), clean=simple_clean)
    assert list(payload) == ["id", "title", "location", "content", "departments"]
    assert payload["id"] == "8249901"
    assert payload["title"] == "Software Engineer"
    assert payload["location"] == {"name": "Seattle, WA"}
    assert payload["departments"] == [{"name": "Global Operations"}]
    assert "<" not in payload["content"] and "&lt;" not in payload["content"]


def test_posting_payload_has_no_url() -> None:
    posting = handcheck_posting("8249901")
    payload = build_posting_payload(posting, clean=lambda s: "cleaned")
    text = json.dumps(payload)
    assert "absolute_url" not in text
    assert "gh_jid" not in text
    assert "ai_opt_out" not in text
    assert "http" not in text


def test_posting_payload_omits_missing_location() -> None:
    posting = small_posting(location=None)
    payload = build_posting_payload(posting, clean=simple_clean)
    assert "location" not in payload


def test_payload_deterministic() -> None:
    resume_a = build_resume_payload(make_resume())
    resume_b = build_resume_payload(make_resume())
    posting = handcheck_posting("8234357")
    posting_a = build_posting_payload(posting, clean=simple_clean)
    posting_b = build_posting_payload(posting, clean=simple_clean)
    assert json.dumps(resume_a) == json.dumps(resume_b)
    assert payload_sha256(resume_a, posting_a) == payload_sha256(resume_b, posting_b)
    other = build_posting_payload(handcheck_posting("8249901"), clean=simple_clean)
    assert payload_sha256(resume_a, posting_a) != payload_sha256(resume_a, other)
