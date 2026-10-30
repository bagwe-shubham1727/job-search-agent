"""WS3-local test doubles for modules other workstreams own (WS1, WS2, WS4).

These are deliberately small stand-ins so the orchestration can be tested before the
real rule, provider, file policy and judge are merged. They are not the real
implementations and are never imported by ``src``:

* ``LocalOutputRoot``: the ``fsio.OutputRoot`` surface (atomic writes, rel checks),
  with failure injection.
* ``StubProvider``: a minimal Greenhouse-shaped parser.
* ``stub_evaluate`` / ``stub_validate``: a toy rule and evidence check.
* ``ScriptedJudge``: a ``ports.Judge`` over ``FakeBackend`` with retry-once and
  separate raw-reply logs.
* ``HttpxFetcher``: an ``HttpFetcher`` over an ``httpx`` mock transport.
"""

from __future__ import annotations

import contextlib
import hashlib
import json
import os
import re
import shutil
from collections.abc import Callable, Iterator, Mapping
from dataclasses import dataclass, field
from datetime import timedelta
from pathlib import Path, PurePosixPath
from typing import Any

import httpx

from job_search_agent.config import AgentConfig
from job_search_agent.errors import InvalidResponse, PathRejected
from job_search_agent.events import EventLog
from job_search_agent.models import (
    AttemptSummary,
    DataQualityCode,
    DataQualityIssue,
    FetchErrorKind,
    FetchResult,
    Gate,
    JudgmentDiagnostic,
    JudgmentOutcome,
    JudgmentReply,
    JudgmentStatus,
    LocationCheck,
    LocationLabel,
    ModelJudgment,
    ParsedBoard,
    Posting,
    RuleVerdict,
    Severity,
    SkillEvidence,
    VerdictLabel,
    VerifiedResume,
)
from job_search_agent.pipeline import OutputWriter, RunDeps
from job_search_agent.ports import RawSource
from job_search_agent.sources import LiveSource, ReplaySource
from tests.conftest import (
    FIXED_START,
    HANDCHECK_META_REL,
    HANDCHECK_RAW_REL,
    PINNED_RESUME_SHA256,
    REPO_ROOT,
    RESUME_FIXTURE_REL,
)
from tests.fakes import FakeBackend, FakeGit, FixedClock, RecordingTransport, Reply
from tests.fakes import mock_transport as make_transport

JOBS_URL = "https://boards-api.greenhouse.io/v1/boards/stripe/jobs?content=true"
CONSTRUCTED_ID = 999000001
"""ID of the posting added to constructed variants of the hand-check response."""

VALID_REPLY = json.dumps(
    {
        "label": "RELEVANT",
        "summary": "Constructed fake reply for tests.",
        "evidence": [
            {
                "resume_path": "$.skills.languages[0]",
                "posting_path": "$.content",
                "reason": "constructed",
            }
        ],
        "uncertainties": [],
    }
)


# --- résumé -------------------------------------------------------------------


def fixture_resume() -> VerifiedResume:
    """Builds a ``VerifiedResume`` of the committed fixture without the WS2 gate."""
    data = (REPO_ROOT / RESUME_FIXTURE_REL).read_bytes()
    assert hashlib.sha256(data).hexdigest() == PINNED_RESUME_SHA256
    return VerifiedResume(
        json.loads(data), sha256=PINNED_RESUME_SHA256, source_path=RESUME_FIXTURE_REL
    )


def sensitive_resume_values() -> list[str]:
    """Résumé values that must never appear in outputs (contacts, bullets, ...)."""
    data = json.loads((REPO_ROOT / RESUME_FIXTURE_REL).read_bytes())
    values: list[str] = []
    values += [str(v) for v in data["personal"].values() if isinstance(v, str)]
    for section in ("experience", "projects", "education"):
        for item in data.get(section, []):
            for key, value in item.items():
                if key == "bullets":
                    values += list(value)
                elif isinstance(value, str) and key in (
                    "company",
                    "employer",
                    "school",
                    "institution",
                    "name",
                ):
                    values.append(value)
    return [v for v in values if len(v) >= 6]


# --- output root ----------------------------------------------------------------


class LocalOutputRoot:
    """Minimal stand-in for WS2's ``fsio.OutputRoot``.

    Args:
        root: The data directory (created if needed).
        fail_writes: Data-root rels (or trailing path parts, e.g. ``"records.json"``)
            whose writes raise ``OSError`` (failure injection).
    """

    def __init__(self, root: Path, *, fail_writes: set[str] | None = None) -> None:
        self.root = root
        root.mkdir(parents=True, exist_ok=True)
        self.fail_writes = fail_writes if fail_writes is not None else set()

    def resolve_for_write(self, rel: str) -> Path:
        pure = PurePosixPath(rel)
        if not rel or pure.is_absolute() or ".." in pure.parts or "\x00" in rel:
            raise PathRejected("invalid", rel)
        return self.root / rel

    def _check_fail(self, rel: str) -> None:
        if any(rel == f or rel.endswith("/" + f) for f in self.fail_writes):
            raise OSError(f"injected write failure: {rel}")

    def write_bytes_atomic(self, rel: str, data: bytes) -> Path:
        path = self.resolve_for_write(rel)
        self._check_fail(rel)
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_name(path.name + ".tmp")
        tmp.write_bytes(data)
        os.replace(tmp, path)
        return path

    def write_json_atomic(self, rel: str, obj: Any, *, sort_keys: bool = True) -> Path:
        text = json.dumps(obj, indent=2, sort_keys=sort_keys, ensure_ascii=False)
        return self.write_bytes_atomic(rel, (text + "\n").encode("utf-8"))

    def append_jsonl(self, rel: str, obj: Any) -> Path:
        path = self.resolve_for_write(rel)
        self._check_fail(rel)
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(obj, sort_keys=True) + "\n")
        return path

    def make_empty_dir(self, rel: str) -> Path:
        path = self.resolve_for_write(rel)
        path.mkdir(parents=True, exist_ok=False)
        return path

    def read_bytes(self, rel: str) -> bytes:
        return self.resolve_for_write(rel).read_bytes()

    def exists(self, rel: str) -> bool:
        return self.resolve_for_write(rel).exists()

    @contextlib.contextmanager
    def lock(self, rel: str) -> Iterator[None]:
        self.resolve_for_write(rel)
        yield


# --- provider -------------------------------------------------------------------


class StubProvider:
    """Greenhouse-shaped parser (stand-in for WS1 ``GreenhouseProvider``)."""

    @property
    def name(self) -> str:
        return "greenhouse"

    def jobs_url(self, board_token: str) -> str:
        return f"https://boards-api.greenhouse.io/v1/boards/{board_token}/jobs?content=true"

    def parse(self, body: bytes) -> ParsedBoard:
        try:
            obj = json.loads(body)
        except ValueError as exc:
            raise InvalidResponse("not_json") from exc
        if not isinstance(obj, dict):
            raise InvalidResponse("not_object")
        jobs = obj.get("jobs")
        if not isinstance(jobs, list):
            raise InvalidResponse("jobs_not_list")
        meta = obj.get("meta")
        total = meta.get("total") if isinstance(meta, dict) else None
        if not isinstance(total, int) or isinstance(total, bool):
            raise InvalidResponse("meta_total")
        postings: list[Posting] = []
        issues: list[DataQualityIssue] = []
        seen: set[str] = set()
        for index, job in enumerate(jobs):
            raw_id = job.get("id") if isinstance(job, dict) else None
            if (
                not isinstance(job, dict)
                or not isinstance(raw_id, int)
                or isinstance(raw_id, bool)
                or raw_id <= 0
            ):
                issues.append(
                    DataQualityIssue(
                        code=DataQualityCode.INVALID_ID,
                        severity=Severity.ERROR,
                        index=index,
                    )
                )
                continue
            pid = str(raw_id)
            if pid in seen:
                continue
            seen.add(pid)
            location = job.get("location")
            name = location.get("name") if isinstance(location, dict) else None
            postings.append(
                Posting(
                    posting_id=pid,
                    index=index,
                    raw=job,
                    title=job.get("title") or "",
                    location_name=name if isinstance(name, str) else None,
                    updated_at=job.get("updated_at")
                    if isinstance(job.get("updated_at"), str)
                    else None,
                    content_raw=job.get("content") or "",
                    department_names=tuple(
                        d.get("name") or "" for d in job.get("departments") or []
                    ),
                )
            )
        if jobs and not postings:
            raise InvalidResponse("no_valid_ids")
        return ParsedBoard(
            postings=tuple(postings),
            fetched_count=len(jobs),
            meta_total=total,
            data_quality=tuple(issues),
        )


# --- rule -----------------------------------------------------------------------

_SKILL_ARRAYS = (
    "languages",
    "frontend",
    "backend",
    "data",
    "messaging",
    "cloud_devops",
    "observability",
)


def stub_evaluate(posting: Posting, resume: VerifiedResume) -> RuleVerdict:
    """A toy rule: case-sensitive whole-word skill hits in the content."""
    data = resume.to_dict()
    evidence: list[SkillEvidence] = []
    for array in _SKILL_ARRAYS:
        for i, term in enumerate(data["skills"][array]):
            pattern = r"(?<![A-Za-z0-9])" + re.escape(term) + r"(?![A-Za-z0-9#])"
            if re.search(pattern, posting.content_raw):
                evidence.append(
                    SkillEvidence(
                        term=term,
                        resume_path=f"$.skills.{array}[{i}]",
                        posting_path="$.content",
                    )
                )
    failed: list[Gate] = []
    if "Engineer" not in posting.title or "Senior" in posting.title:
        failed.append(Gate.TITLE)
    if len(evidence) < 2:
        failed.append(Gate.SKILLS)
    us = posting.location_name is not None and posting.location_name.endswith(", US")
    if not us:
        failed.append(Gate.LOCATION)
    location = LocationCheck(
        label=LocationLabel.US_BASED if us else LocationLabel.NOT_ESTABLISHED,
        evidence=["$.location.name" if posting.location_name is not None else "$.id"],
        reason="stub location check",
    )
    return RuleVerdict(
        label=VerdictLabel.NO_MATCH if failed else VerdictLabel.MATCH,
        location_check=location,
        evidence=evidence,
        reason="stub rule",
        failed_gates=failed,
    )


def _resolve_skill(resume_data: Mapping[str, Any], path: str) -> object:
    match = re.fullmatch(r"\$\.skills\.(\w+)\[(\d+)\]", path)
    if not match:
        return None
    values = resume_data.get("skills", {}).get(match.group(1), [])
    index = int(match.group(2))
    return values[index] if index < len(values) else None


def stub_validate(
    verdict: RuleVerdict, raw_posting: Mapping[str, Any], resume_data: Mapping[str, Any]
) -> list[str]:
    """Checks that each evidence term is at its résumé path and in ``$.content``."""
    errors: list[str] = []
    for item in verdict.evidence:
        if _resolve_skill(resume_data, item.resume_path) != item.term:
            errors.append(f"resume_path:{item.term}")
        if item.term not in str(raw_posting.get("content", "")):
            errors.append(f"posting_path:{item.term}")
    return errors


def failing_validate(
    verdict: RuleVerdict, raw_posting: Mapping[str, Any], resume_data: Mapping[str, Any]
) -> list[str]:
    """A validator that reports every verdict invalid (simulates a rule bug)."""
    return ["constructed_failure"]


# --- judge ----------------------------------------------------------------------


class ScriptedJudge:
    """``ports.Judge`` over a ``FakeBackend``: retry once after validation failure.

    Raw replies are written to ``<log_dir>/attempt-<n>.json`` through the writer and
    never into the judgment.
    """

    def __init__(
        self, backend: FakeBackend, out: LocalOutputRoot, config: AgentConfig
    ) -> None:
        self.backend = backend
        self.out = out
        self.config = config
        self.judged: list[str] = []

    def judge(
        self, posting: Posting, resume: VerifiedResume, *, log_dir: str
    ) -> JudgmentOutcome:
        assert isinstance(resume, VerifiedResume)
        self.judged.append(posting.posting_id)
        availability = self.backend.availability()
        if not availability.available:
            return JudgmentOutcome(
                posting.posting_id,
                ModelJudgment(
                    status=JudgmentStatus.UNAVAILABLE,
                    diagnostic=JudgmentDiagnostic(
                        unavailable_reason=availability.reason
                    ),
                ),
            )
        attempts: list[AttemptSummary] = []
        for n in (1, 2):
            reply = self.backend.complete(f"judge posting {posting.posting_id}")
            rel = f"{log_dir}/attempt-{n}.json"
            self.out.write_json_atomic(
                rel, {"stdout_raw": reply.raw_stdout, "attempt": n}
            )
            ref = self.config.repo_rel(rel)
            if not reply.ok or reply.result_text is None:
                attempts.append(
                    AttemptSummary(
                        attempt=n,
                        raw_log_ref=ref,
                        first_reply=n == 1,
                        validation_passed=None,
                        backend_error=reply.error,
                    )
                )
                return _outcome(posting, JudgmentStatus.ERROR, attempts)
            try:
                parsed = JudgmentReply.model_validate(
                    json.loads(reply.result_text), strict=True
                )
            except ValueError:
                attempts.append(
                    AttemptSummary(
                        attempt=n,
                        raw_log_ref=ref,
                        first_reply=n == 1,
                        validation_passed=False,
                        validation_codes=["schema"],
                    )
                )
                continue
            attempts.append(
                AttemptSummary(
                    attempt=n,
                    raw_log_ref=ref,
                    first_reply=n == 1,
                    validation_passed=True,
                )
            )
            return JudgmentOutcome(
                posting.posting_id,
                ModelJudgment(
                    status=JudgmentStatus.VALID,
                    label=parsed.label,
                    summary=parsed.summary,
                    evidence=list(parsed.evidence),
                    uncertainties=list(parsed.uncertainties),
                    diagnostic=JudgmentDiagnostic(attempts=attempts),
                ),
            )
        return _outcome(posting, JudgmentStatus.INVALID_OUTPUT, attempts)


def _outcome(
    posting: Posting, status: JudgmentStatus, attempts: list[AttemptSummary]
) -> JudgmentOutcome:
    return JudgmentOutcome(
        posting.posting_id,
        ModelJudgment(status=status, diagnostic=JudgmentDiagnostic(attempts=attempts)),
    )


# --- http -----------------------------------------------------------------------


class HttpxFetcher:
    """``HttpFetcher`` over an httpx transport (no allow-list; that is WS2's)."""

    def __init__(self, transport: httpx.BaseTransport) -> None:
        self._client = httpx.Client(transport=transport)

    def get(self, url: str) -> FetchResult:
        response = self._client.get(url)
        ok = 200 <= response.status_code < 300
        return FetchResult(
            requested_url=url,
            final_url=str(response.url),
            redirect_chain=(),
            status_code=response.status_code,
            headers={k.lower(): v for k, v in response.headers.items()},
            body=response.content,
            error=None if ok else FetchErrorKind.HTTP_STATUS,
        )


class FailingFetcher:
    """``HttpFetcher`` whose every request fails at the transport (no body)."""

    def __init__(self) -> None:
        self.calls = 0

    def get(self, url: str) -> FetchResult:
        self.calls += 1
        return FetchResult(
            requested_url=url,
            final_url=None,
            redirect_chain=(),
            status_code=None,
            headers={},
            body=None,
            error=FetchErrorKind.TRANSPORT,
            error_detail="constructed transport failure",
        )


# --- harness --------------------------------------------------------------------


def handcheck_body() -> bytes:
    """The committed §13 raw response bytes."""
    return (REPO_ROOT / HANDCHECK_RAW_REL).read_bytes()


def constructed_with_added_posting(body: bytes, *, title: str) -> bytes:
    """CONSTRUCTED variant: the hand-check response plus one new posting."""
    obj = json.loads(body)
    extra = dict(obj["jobs"][0])
    extra["id"] = CONSTRUCTED_ID
    extra["title"] = title
    extra["location"] = {"name": "New York, NY, US"}
    extra["content"] = "&lt;p&gt;We use TypeScript and React and Python.&lt;/p&gt;"
    obj["jobs"].append(extra)
    obj["meta"]["total"] = len(obj["jobs"])
    return json.dumps(obj).encode("utf-8")


def constructed_without(body: bytes, posting_id: int) -> bytes:
    """CONSTRUCTED variant: the response with one posting removed."""
    obj = json.loads(body)
    obj["jobs"] = [j for j in obj["jobs"] if j.get("id") != posting_id]
    obj["meta"]["total"] = len(obj["jobs"])
    return json.dumps(obj).encode("utf-8")


def make_config(project_root: Path, *, backend: str = "claude-cli") -> AgentConfig:
    """An ``AgentConfig`` rooted at a temporary project directory."""
    return AgentConfig.model_validate(
        {
            "project_root": project_root,
            "board": {"provider": "greenhouse", "token": "stripe"},
            "http": {
                "allowed_hosts": ["boards-api.greenhouse.io"],
                "timeout_s": 5.0,
                "max_bytes": 50_000_000,
                "max_redirects": 3,
                "user_agent": "test",
            },
            "resume": {
                "path": RESUME_FIXTURE_REL,
                "pinned_sha256": PINNED_RESUME_SHA256,
            },
            "model": {
                "backend": backend,
                "executable": "claude",
                "model_id": "claude-sonnet-5-5",
                "timeout_s": 5.0,
                "prompt_version": "v1",
            },
        }
    )


@dataclass
class Harness:
    """A temporary project with every WS3 collaborator wired to a double."""

    root: Path
    config: AgentConfig
    out: LocalOutputRoot
    clock: FixedClock
    git: FakeGit
    backend: FakeBackend
    judge: ScriptedJudge
    provider: StubProvider = field(default_factory=StubProvider)
    terminal_lines: list[str] = field(default_factory=list)
    transports: list[RecordingTransport] = field(default_factory=list)
    events: list[EventLog] = field(default_factory=list)

    @classmethod
    def create(cls, root: Path, *, backend: FakeBackend | None = None) -> Harness:
        config = make_config(root)
        out = LocalOutputRoot(config.data_dir)
        fake = backend if backend is not None else FakeBackend()
        for rel in (HANDCHECK_RAW_REL, HANDCHECK_META_REL):
            (root / rel).parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(REPO_ROOT / rel, root / rel)
        return cls(
            root=root,
            config=config,
            out=out,
            clock=FixedClock(FIXED_START, step=timedelta(seconds=1)),
            git=FakeGit(head_commit="a" * 40),
            backend=fake,
            judge=ScriptedJudge(fake, out, config),
        )

    def set_backend(self, backend: FakeBackend) -> None:
        self.backend = backend
        self.judge = ScriptedJudge(backend, self.out, self.config)

    def live_source(self, reply: Reply) -> LiveSource:
        transport = make_transport({JOBS_URL: reply})
        self.transports.append(transport)
        return LiveSource(HttpxFetcher(transport), JOBS_URL)

    def replay_source(self, repo_rel: str = HANDCHECK_RAW_REL) -> ReplaySource:
        return ReplaySource(self.root / repo_rel, repo_rel)

    def deps(
        self,
        source: RawSource,
        *,
        seeded: bool = False,
        use_judge: bool = True,
        load_resume: Callable[[], VerifiedResume] = fixture_resume,
        validate: Callable[
            [RuleVerdict, Mapping[str, Any], Mapping[str, Any]], list[str]
        ] = stub_validate,
        out: OutputWriter | None = None,
    ) -> RunDeps:
        log = EventLog()
        self.events.append(log)
        return RunDeps(
            config=self.config,
            clock=self.clock,
            source=source,
            provider=self.provider,
            load_resume=load_resume,
            evaluate=stub_evaluate,
            validate_evidence=validate,
            judge=self.judge if use_judge else None,
            out=out if out is not None else self.out,
            git=self.git,
            events=log,
            seeded=seeded,
            read_repo_file=lambda rel: (self.root / rel).read_bytes(),
            terminal=self.terminal_lines.append,
        )

    def data(self, rel: str) -> Path:
        return self.config.data_dir / rel

    def run_dir(self, run_id: str, *, seeded: bool = False) -> Path:
        return self.data(f"{'seeded' if seeded else 'live'}/runs/{run_id}")

    def all_output_text(self) -> str:
        parts = [
            p.read_text(encoding="utf-8", errors="replace")
            for p in sorted(self.config.data_dir.rglob("*"))
            if p.is_file() and p.name != "greenhouse-stripe.json"
        ]
        return "\n".join(parts + self.terminal_lines)
