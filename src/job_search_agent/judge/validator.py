"""Strict validator for Claude's judgment reply (CONTRACT §8, PLAN §5.4).

The validator is pure: it reads the reply text and the two payloads that were
actually sent (A18) and returns either a ``ValidJudgment`` or a ``Rejection``. It
never edits, trims into, re-fences or otherwise repairs the text; a rejection keeps
the original text byte for byte.

Steps:

1. Framing. After removing JSON-grammar whitespace (space, tab, LF, CR) at both ends
   (A15), the text must start with ``{`` and end with ``}``. Code fences, prose before
   or after, a top-level array and empty text are rejected with distinct codes.
2. Parsing. ``json.loads`` with a hook that rejects duplicate keys at any depth and a
   hook that rejects ``NaN``, ``Infinity`` and ``-Infinity``.
3. Schema. ``models.JudgmentReply.model_validate(obj, strict=True)``: exactly the four
   keys at the top, exactly three keys per evidence entry, the two labels, the exact
   types, at least one evidence entry (A16) and a non-empty ``reason``.
4. Paths. Every ``resume_path`` must resolve in the résumé payload and every
   ``posting_path`` in the posting payload; the root ``$`` is not a real path (A17).
"""

from __future__ import annotations

import json
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from pydantic import ValidationError

from job_search_agent import jsonpath
from job_search_agent.models import JudgmentReply
from job_search_agent.strict_json import (
    DuplicateKeyError,
    NonStandardConstantError,
    reject_constant,
    reject_duplicate_keys,
)

PathResolver = Callable[[Any, str], Any]
"""``resolve(document, path) -> value``; the default is WS1's ``jsonpath.resolve``.

Must raise ``ValueError`` for a malformed path (``jsonpath.JsonPathSyntaxError``) and
``LookupError`` for a path that does not exist (``jsonpath.PathNotFoundError``).
"""

_JSON_WHITESPACE = " \t\n\r"


class RejectionCode(StrEnum):
    """Why a reply was rejected. Several codes can apply to one reply."""

    EMPTY = "EMPTY"
    CODE_FENCE = "CODE_FENCE"
    TOP_LEVEL_NOT_OBJECT = "TOP_LEVEL_NOT_OBJECT"
    TEXT_OUTSIDE_OBJECT = "TEXT_OUTSIDE_OBJECT"
    """Prose (or anything else) before the opening or after the closing brace."""
    NOT_JSON = "NOT_JSON"
    DUPLICATE_KEY = "DUPLICATE_KEY"
    NON_FINITE_NUMBER = "NON_FINITE_NUMBER"
    MISSING_KEY = "MISSING_KEY"
    EXTRA_KEY = "EXTRA_KEY"
    BAD_LABEL = "BAD_LABEL"
    WRONG_TYPE = "WRONG_TYPE"
    EMPTY_EVIDENCE = "EMPTY_EVIDENCE"
    EMPTY_REASON = "EMPTY_REASON"
    PATH_SYNTAX = "PATH_SYNTAX"
    PATH_IS_ROOT = "PATH_IS_ROOT"
    RESUME_PATH_NOT_FOUND = "RESUME_PATH_NOT_FOUND"
    POSTING_PATH_NOT_FOUND = "POSTING_PATH_NOT_FOUND"


@dataclass(frozen=True, slots=True)
class ValidJudgment:
    """A reply that passed every check.

    Attributes:
        reply: The parsed reply; the only source of a record's structured fields.
    """

    reply: JudgmentReply


@dataclass(frozen=True, slots=True)
class Rejection:
    """A reply that failed validation. Nothing in it was repaired.

    Attributes:
        codes: Every reason found, without duplicates, in discovery order.
        details: Short, value-free notes such as ``"evidence.0.reason"``.
        original_text: The reply text exactly as received.
    """

    codes: tuple[RejectionCode, ...]
    details: tuple[str, ...]
    original_text: str


ValidationResult = ValidJudgment | Rejection


@dataclass(frozen=True, slots=True)
class PathFindings:
    """Evidence-path existence for a reply that parsed as a JSON object.

    Used by the experiment metrics ("evidence-path validity"), which also look at
    replies that parse but fail the schema.

    Attributes:
        entries: Number of evidence entries that are JSON objects.
        valid_entries: Entries whose ``resume_path`` and ``posting_path`` both exist.
    """

    entries: int
    valid_entries: int

    @property
    def has_bad_path(self) -> bool:
        """True when at least one entry cites a path that does not exist."""
        return self.valid_entries < self.entries


def _framing_codes(text: str) -> list[RejectionCode]:
    """Returns the framing problems of ``text`` (empty list when the frame is ok)."""
    core = text.strip(_JSON_WHITESPACE)
    if not core:
        return [RejectionCode.EMPTY]
    if core.startswith("{") and core.endswith("}"):
        return []
    if "```" in core:
        return [RejectionCode.CODE_FENCE]
    if core.startswith("["):
        return [RejectionCode.TOP_LEVEL_NOT_OBJECT]
    if "{" in core:
        return [RejectionCode.TEXT_OUTSIDE_OBJECT]
    return [RejectionCode.NOT_JSON]


def parse_reply_object(text: str) -> dict[str, Any] | Rejection:
    """Runs steps 1 and 2 only: framing and strict JSON parsing.

    Args:
        text: The reply text as received.

    Returns:
        The parsed top-level object, or a ``Rejection``.
    """
    codes = _framing_codes(text)
    if codes:
        return Rejection(tuple(codes), (), text)
    try:
        obj = json.loads(
            text,
            object_pairs_hook=reject_duplicate_keys,
            parse_constant=reject_constant,
        )
    except DuplicateKeyError:
        return Rejection((RejectionCode.DUPLICATE_KEY,), (), text)
    except NonStandardConstantError:
        return Rejection((RejectionCode.NON_FINITE_NUMBER,), (), text)
    except (json.JSONDecodeError, RecursionError):
        return Rejection((RejectionCode.NOT_JSON,), (), text)
    if not isinstance(obj, dict):  # pragma: no cover - the frame guarantees an object
        return Rejection((RejectionCode.TOP_LEVEL_NOT_OBJECT,), (), text)
    return obj


def _schema_code(error_type: str, loc: tuple[int | str, ...]) -> RejectionCode:
    if error_type == "missing":
        return RejectionCode.MISSING_KEY
    if error_type == "extra_forbidden":
        return RejectionCode.EXTRA_KEY
    if loc == ("label",):
        return RejectionCode.BAD_LABEL
    if error_type == "too_short" and loc == ("evidence",):
        return RejectionCode.EMPTY_EVIDENCE
    if error_type == "string_too_short" and loc[-1:] == ("reason",):
        return RejectionCode.EMPTY_REASON
    return RejectionCode.WRONG_TYPE


def _check_path(
    path: str,
    document: Mapping[str, Any],
    not_found: RejectionCode,
    resolver: PathResolver,
) -> RejectionCode | None:
    """Returns why ``path`` is not a real path in ``document``, or ``None``."""
    if path == "$":
        return RejectionCode.PATH_IS_ROOT
    try:
        resolver(document, path)
    except LookupError:
        return not_found
    except ValueError:
        return RejectionCode.PATH_SYNTAX
    return None


def validate_reply(
    text: str,
    resume_payload: Mapping[str, Any],
    posting_payload: Mapping[str, Any],
    *,
    resolver: PathResolver = jsonpath.resolve,
) -> ValidationResult:
    """Validates one reply against CONTRACT §8.

    Args:
        text: Claude's reply text (the CLI envelope's ``result``), unmodified.
        resume_payload: The résumé object exactly as sent in the prompt.
        posting_payload: The posting object exactly as sent in the prompt.
        resolver: Path resolver; see ``PathResolver``.

    Returns:
        ``ValidJudgment`` if every check passes, else ``Rejection`` carrying
        ``text`` unchanged.
    """
    parsed = parse_reply_object(text)
    if isinstance(parsed, Rejection):
        return parsed
    try:
        reply = JudgmentReply.model_validate(parsed, strict=True)
    except ValidationError as exc:
        codes: list[RejectionCode] = []
        details: list[str] = []
        for error in exc.errors(include_input=False, include_url=False):
            loc = tuple(error["loc"])
            code = _schema_code(error["type"], loc)
            if code not in codes:
                codes.append(code)
            details.append(".".join(str(part) for part in loc) or "<root>")
        return Rejection(tuple(codes), tuple(details), text)

    path_codes: list[RejectionCode] = []
    path_details: list[str] = []
    for number, entry in enumerate(reply.evidence):
        for field_name, path, document, not_found in (
            (
                "resume_path",
                entry.resume_path,
                resume_payload,
                RejectionCode.RESUME_PATH_NOT_FOUND,
            ),
            (
                "posting_path",
                entry.posting_path,
                posting_payload,
                RejectionCode.POSTING_PATH_NOT_FOUND,
            ),
        ):
            problem = _check_path(path, document, not_found, resolver)
            if problem is not None:
                if problem not in path_codes:
                    path_codes.append(problem)
                path_details.append(f"evidence.{number}.{field_name}")
    if path_codes:
        return Rejection(tuple(path_codes), tuple(path_details), text)
    return ValidJudgment(reply)


def evidence_path_findings(
    text: str,
    resume_payload: Mapping[str, Any],
    posting_payload: Mapping[str, Any],
    *,
    resolver: PathResolver = jsonpath.resolve,
) -> PathFindings | None:
    """Measures evidence-path existence in any reply that parses as a JSON object.

    Unlike ``validate_reply`` this ignores schema errors: every object inside an
    ``evidence`` list is counted, and an entry is valid only when both paths are
    strings that resolve (and neither is the root).

    Args:
        text: The reply text.
        resume_payload: The résumé object as sent.
        posting_payload: The posting object as sent.
        resolver: Path resolver.

    Returns:
        The findings, or ``None`` when the reply does not parse as a JSON object
        (or has no ``evidence`` list), so it has no paths to measure.
    """
    parsed = parse_reply_object(text)
    if isinstance(parsed, Rejection):
        return None
    evidence = parsed.get("evidence")
    if not isinstance(evidence, list):
        return None
    entries = 0
    valid = 0
    for item in evidence:
        if not isinstance(item, dict):
            continue
        entries += 1
        resume_path = item.get("resume_path")
        posting_path = item.get("posting_path")
        if not isinstance(resume_path, str) or not isinstance(posting_path, str):
            continue
        resume_problem = _check_path(
            resume_path,
            resume_payload,
            RejectionCode.RESUME_PATH_NOT_FOUND,
            resolver,
        )
        posting_problem = _check_path(
            posting_path,
            posting_payload,
            RejectionCode.POSTING_PATH_NOT_FOUND,
            resolver,
        )
        if resume_problem is None and posting_problem is None:
            valid += 1
    return PathFindings(entries=entries, valid_entries=valid)
