"""Test doubles for the judge and experiment tests.

* ``MemoryWriter``: an ``OutputRoot``-shaped writer that also keeps every JSON
  document in memory (``.json``), so tests can assert on what was written.
* ``valid_reply``: a reply object that passes the CONTRACT §8 validator.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


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
