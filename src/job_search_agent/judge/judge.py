"""Judging one posting: render, call, validate, retry once, log (PLAN §5.5).

* The call is made only when ``backend.availability()`` says so; otherwise the
  judgment is ``UNAVAILABLE`` and nothing is called or logged.
* A failed call (spawn, timeout, non-zero exit, bad envelope, ``is_error``) is
  ``ERROR`` and is **not** retried; the pipeline keeps the posting pending.
* A reply that fails validation is retried **once** (when ``retry_once``) with the
  byte-identical prompt in a new process. Two invalid replies give
  ``INVALID_OUTPUT``. Experiments pass ``retry_once=False`` and score the first reply.
* Every attempt writes its own raw-reply log file. Only a ``ValidJudgment`` fills the
  record's structured fields; the record holds just pointers to the logs.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Literal

from pydantic import AwareDatetime, BaseModel, ConfigDict

from job_search_agent import jsonpath
from job_search_agent.clock import format_run_id, to_eastern
from job_search_agent.config import ModelSettings
from job_search_agent.judge.backend import (
    ADDED_ENV,
    STRIPPED_ENV,
    ClaudeCliBackend,
    MakeEmptyDir,
    UnavailableBackend,
)
from job_search_agent.judge.payload import (
    Cleaner,
    build_posting_payload,
    build_resume_payload,
    payload_sha256,
    render_json,
)
from job_search_agent.judge.prompt import PromptContract
from job_search_agent.judge.rawlog import (
    AttemptValidation,
    JsonWriter,
    RawAttemptLog,
    RawReplyLog,
)
from job_search_agent.judge.validator import (
    PathResolver,
    Rejection,
    ValidationResult,
    ValidJudgment,
    validate_reply,
)
from job_search_agent.models import (
    AttemptSummary,
    BackendErrorKind,
    BackendReply,
    JudgmentDiagnostic,
    JudgmentOutcome,
    JudgmentStatus,
    ModelJudgment,
    Posting,
    VerifiedResume,
)
from job_search_agent.ports import Clock, CommandRunner, ModelBackend
from job_search_agent.privacy import sensitive_values
from job_search_agent.resume import PERSONA_LABEL


@dataclass(frozen=True, slots=True)
class JudgeAttempt:
    """One model call made while judging a posting.

    Attributes:
        attempt: 1 or 2.
        reply: The backend's reply (failures included).
        validation: The validator result, or ``None`` when the call failed.
        raw_log_ref: Repo-relative path of this attempt's raw-reply log.
    """

    attempt: int
    reply: BackendReply
    validation: ValidationResult | None
    raw_log_ref: str


@dataclass(frozen=True, slots=True)
class JudgeRun:
    """Everything about one posting's judgment, for experiments and tests.

    Attributes:
        outcome: What the pipeline stores.
        attempts: The calls made, in order (empty when UNAVAILABLE).
        resume_payload: The résumé object sent (``None`` when UNAVAILABLE).
        posting_payload: The posting object sent (``None`` when UNAVAILABLE).
    """

    outcome: JudgmentOutcome
    attempts: tuple[JudgeAttempt, ...]
    resume_payload: Mapping[str, Any] | None
    posting_payload: Mapping[str, Any] | None


def _validation_log(result: ValidationResult | None) -> AttemptValidation:
    if result is None:
        return AttemptValidation(passed=None)
    if isinstance(result, ValidJudgment):
        return AttemptValidation(passed=True)
    return AttemptValidation(passed=False, codes=[c.value for c in result.codes])


def _summary(attempt: JudgeAttempt) -> AttemptSummary:
    result = attempt.validation
    return AttemptSummary(
        attempt=attempt.attempt,
        raw_log_ref=attempt.raw_log_ref,
        first_reply=attempt.attempt == 1,
        validation_passed=None if result is None else isinstance(result, ValidJudgment),
        validation_codes=(
            [c.value for c in result.codes] if isinstance(result, Rejection) else []
        ),
        session_id=attempt.reply.session_id,
        backend_error=attempt.reply.error,
    )


def echo_allow_list(resume_payload: Mapping[str, Any]) -> tuple[str, ...]:
    """Returns the strings a reply may always contain (review fix 5).

    Args:
        resume_payload: The résumé object as sent.

    Returns:
        The persona label and every skill and target phrase that was sent; CONTRACT
        §12 allows matched skill terms and the persona label in outputs.
    """
    allowed = [PERSONA_LABEL]
    for section in ("skills", "target"):
        arrays = resume_payload.get(section)
        if isinstance(arrays, Mapping):
            for items in arrays.values():
                if isinstance(items, list):
                    allowed += [item for item in items if isinstance(item, str)]
    return tuple(allowed)


def judge_posting_detailed(
    backend: ModelBackend,
    prompt: PromptContract,
    posting: Posting,
    resume: VerifiedResume,
    rawlog: RawReplyLog,
    *,
    log_dir: str,
    model_requested: str | None,
    retry_once: bool = True,
    clean: Cleaner | None = None,
    resolver: PathResolver = jsonpath.resolve,
    seeded: bool | None = None,
) -> JudgeRun:
    """Judges one posting and returns the outcome plus every attempt.

    Args:
        backend: The model backend.
        prompt: The loaded prompt contract.
        posting: The posting to judge.
        resume: The verified résumé; nothing else is accepted.
        rawlog: Where raw replies are written.
        log_dir: Data-root-relative directory for this posting's attempt files.
        model_requested: The model ID asked for (recorded per call).
        retry_once: Retry once after a validation failure (pipeline); experiments
            pass ``False``.
        clean: HTML cleaner for the posting payload (defaults to WS1's).
        resolver: Path resolver for the validator.
        seeded: Copied into each raw log file when not ``None``.

    Returns:
        The run.

    Raises:
        TypeError: If ``resume`` is not a ``VerifiedResume``.
    """
    if not isinstance(resume, VerifiedResume):
        raise TypeError("the judge accepts only a VerifiedResume (CONTRACT §12)")
    availability = backend.availability()
    if not availability.available:
        judgment = ModelJudgment(
            status=JudgmentStatus.UNAVAILABLE,
            diagnostic=JudgmentDiagnostic(
                prompt_id=prompt.prompt_id,
                prompt_sha256=prompt.sha256,
                model_requested=model_requested,
                unavailable_reason=availability.reason or "unavailable",
            ),
        )
        return JudgeRun(JudgmentOutcome(posting.posting_id, judgment), (), None, None)

    resume_payload = build_resume_payload(resume)
    posting_payload = build_posting_payload(posting, clean=clean)
    digest = payload_sha256(resume_payload, posting_payload)
    text = prompt.render(render_json(resume_payload), render_json(posting_payload))
    echo_values = sensitive_values(resume)
    echo_allow = echo_allow_list(resume_payload)

    attempts: list[JudgeAttempt] = []
    max_attempts = 2 if retry_once else 1
    final: ValidationResult | None = None
    for number in range(1, max_attempts + 1):
        reply = backend.complete(text)
        result: ValidationResult | None = None
        if reply.ok and reply.result_text is not None:
            result = validate_reply(
                reply.result_text,
                resume_payload,
                posting_payload,
                resolver=resolver,
                echo_values=echo_values,
                echo_allow=echo_allow,
            )
        entry = RawAttemptLog(
            posting_id=posting.posting_id,
            attempt=number,
            first_reply=number == 1,
            prompt_id=prompt.prompt_id,
            prompt_sha256=prompt.sha256,
            payload_sha256=digest,
            model_requested=model_requested,
            model_served=list(reply.model_served),
            claude_version=availability.version,
            argv=list(reply.argv),
            started_at_utc=reply.started_at_utc,
            started_at_et=to_eastern(reply.started_at_utc),
            duration_ms=reply.duration_ms,
            exit_code=reply.exit_code,
            stdout_raw=reply.raw_stdout,
            stderr=reply.stderr,
            session_id=reply.session_id,
            is_error=reply.is_error,
            total_cost_usd=reply.total_cost_usd,
            backend_error=reply.error,
            validation=_validation_log(result),
            seeded=seeded,
        )
        ref = rawlog.write(log_dir, entry)
        attempts.append(JudgeAttempt(number, reply, result, ref))
        final = result
        if not isinstance(result, Rejection):
            break  # VALID, or a failed call (ERROR is never retried)

    diagnostic = JudgmentDiagnostic(
        prompt_id=prompt.prompt_id,
        prompt_sha256=prompt.sha256,
        model_requested=model_requested,
        attempts=[_summary(a) for a in attempts],
    )
    if isinstance(final, ValidJudgment):
        reply_model = final.reply
        judgment = ModelJudgment(
            status=JudgmentStatus.VALID,
            label=reply_model.label,
            summary=reply_model.summary,
            evidence=list(reply_model.evidence),
            uncertainties=list(reply_model.uncertainties),
            diagnostic=diagnostic,
        )
    elif isinstance(final, Rejection):
        judgment = ModelJudgment(
            status=JudgmentStatus.INVALID_OUTPUT, diagnostic=diagnostic
        )
    else:
        judgment = ModelJudgment(status=JudgmentStatus.ERROR, diagnostic=diagnostic)
    return JudgeRun(
        JudgmentOutcome(posting.posting_id, judgment),
        tuple(attempts),
        resume_payload,
        posting_payload,
    )


def judge_posting(
    backend: ModelBackend,
    prompt: PromptContract,
    posting: Posting,
    resume: VerifiedResume,
    rawlog: RawReplyLog,
    *,
    log_dir: str,
    model_requested: str | None,
    retry_once: bool = True,
    clean: Cleaner | None = None,
    resolver: PathResolver = jsonpath.resolve,
    seeded: bool | None = None,
) -> JudgmentOutcome:
    """Judges one posting (see ``judge_posting_detailed``) and returns the outcome.

    Args:
        backend: The model backend.
        prompt: The loaded prompt contract.
        posting: The posting to judge.
        resume: The verified résumé.
        rawlog: Where raw replies are written.
        log_dir: Data-root-relative directory for this posting's attempt files.
        model_requested: The model ID asked for.
        retry_once: Retry once after a validation failure.
        clean: HTML cleaner for the posting payload.
        resolver: Path resolver for the validator.
        seeded: Copied into each raw log file when not ``None`` (replay runs).

    Returns:
        The judgment outcome.
    """
    return judge_posting_detailed(
        backend,
        prompt,
        posting,
        resume,
        rawlog,
        log_dir=log_dir,
        model_requested=model_requested,
        retry_once=retry_once,
        clean=clean,
        resolver=resolver,
        seeded=seeded,
    ).outcome


class CliJudge:
    """``ports.Judge`` adapter used by the pipeline (WS3).

    Args:
        backend: The model backend (``ClaudeCliBackend`` or ``UnavailableBackend``).
        prompt: The prompt contract (``[model].prompt_version``).
        rawlog: Raw-reply log writer.
        model_requested: The pinned model ID, recorded per call.
        clean: HTML cleaner (defaults to WS1's ``text.clean_html``).
        resolver: Validator path resolver.
        seeded: Written into every raw log file when not ``None`` (``True`` for
            replay runs, so the seeded label reaches every file).
    """

    def __init__(
        self,
        backend: ModelBackend,
        prompt: PromptContract,
        rawlog: RawReplyLog,
        *,
        model_requested: str | None,
        clean: Cleaner | None = None,
        resolver: PathResolver = jsonpath.resolve,
        seeded: bool | None = None,
    ) -> None:
        self._backend = backend
        self._seeded = seeded
        self._prompt = prompt
        self._rawlog = rawlog
        self._model_requested = model_requested
        self._clean = clean
        self._resolver = resolver

    def judge(
        self, posting: Posting, resume: VerifiedResume, *, log_dir: str
    ) -> JudgmentOutcome:
        """Judges one posting, retrying once after a validation failure only.

        Args:
            posting: The posting.
            resume: The verified résumé.
            log_dir: Data-root-relative directory for raw-reply logs.

        Returns:
            The outcome.
        """
        return judge_posting(
            self._backend,
            self._prompt,
            posting,
            resume,
            self._rawlog,
            log_dir=log_dir,
            model_requested=self._model_requested,
            retry_once=True,
            clean=self._clean,
            resolver=self._resolver,
            seeded=self._seeded,
        )


def build_backend(
    settings: ModelSettings,
    *,
    runner: CommandRunner,
    make_empty_dir: MakeEmptyDir,
    clock: Clock,
) -> ClaudeCliBackend | UnavailableBackend:
    """Builds the configured backend.

    Args:
        settings: ``[model]`` from ``config/agent.toml`` (after CLI overrides).
        runner: The command runner (``sysio.SubprocessRunner`` in production).
        make_empty_dir: ``OutputRoot.make_empty_dir``.
        clock: The clock.

    Returns:
        ``UnavailableBackend("backend_none")`` for ``backend = "none"``, else a
        ``ClaudeCliBackend``.
    """
    if settings.backend == "none":
        return UnavailableBackend("backend_none")
    return ClaudeCliBackend(
        executable=settings.executable,
        model_id=settings.model_id,
        timeout_s=settings.timeout_s,
        runner=runner,
        make_empty_dir=make_empty_dir,
        clock=clock,
    )


def build_judge(
    settings: ModelSettings,
    prompt: PromptContract,
    *,
    runner: CommandRunner,
    writer: JsonWriter,
    make_empty_dir: MakeEmptyDir,
    clock: Clock,
    repo_rel: Callable[[str], str],
    clean: Cleaner | None = None,
    seeded: bool | None = None,
) -> CliJudge:
    """Wires a ``CliJudge`` from configuration (convenience for the pipeline CLI).

    Args:
        settings: ``[model]`` settings.
        prompt: The loaded prompt for ``settings.prompt_version``.
        runner: The command runner.
        writer: ``OutputRoot`` (atomic JSON writes under the data dir).
        make_empty_dir: ``OutputRoot.make_empty_dir``.
        clock: The clock.
        repo_rel: ``AgentConfig.repo_rel``.
        clean: HTML cleaner (defaults to WS1's).
        seeded: Passed to ``CliJudge`` (``True`` for replay runs).

    Returns:
        The judge.
    """
    backend = build_backend(
        settings, runner=runner, make_empty_dir=make_empty_dir, clock=clock
    )
    return CliJudge(
        backend,
        prompt,
        RawReplyLog(writer, repo_rel=repo_rel),
        model_requested=settings.model_id if settings.backend != "none" else None,
        clean=clean,
        seeded=seeded,
    )


# --- doctor --probe-model -----------------------------------------------------

PROBE_PROMPT = "Reply with exactly the two letters OK and nothing else."
"""A tiny prompt with no résumé or posting content."""


class ProbeReport(BaseModel):
    """Facts from one ``jsa doctor --probe-model`` call (``data/doctor/<ts>.json``)."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    kind: Literal["probe-model"] = "probe-model"
    checked_at_utc: AwareDatetime
    checked_at_et: AwareDatetime
    available: bool
    unavailable_reason: str | None
    claude_version: str | None
    argv: list[str]
    prompt: str
    env_added: dict[str, str]
    env_removed: list[str]
    cwd_kind: Literal["fresh-empty"] = "fresh-empty"
    model_requested: str | None
    model_served: list[str]
    session_id: str | None
    exit_code: int | None
    duration_ms: int | None
    is_error: bool | None
    backend_error: BackendErrorKind | None
    result_text: str | None
    reply_is_ok: bool | None
    """Whether the reply was exactly ``OK`` after trimming whitespace."""
    total_cost_usd: float | None
    stdout_raw: str | None
    stderr: str | None


@dataclass(frozen=True, slots=True)
class ProbeResult:
    """A probe report and where it was written (if a writer was given)."""

    report: ProbeReport
    data_rel: str | None


def probe_model(
    backend: ModelBackend,
    *,
    model_requested: str | None,
    clock: Clock,
    writer: JsonWriter | None = None,
) -> ProbeResult:
    """Makes one tiny real call and records the facts (``jsa doctor --probe-model``).

    Args:
        backend: The backend to probe (normally a ``ClaudeCliBackend``).
        model_requested: The pinned model ID.
        clock: The clock.
        writer: If given, the report is written to ``doctor/<run-id>.json``.

    Returns:
        The report and its data-root-relative path.
    """
    checked: datetime = clock.now_utc()
    availability = backend.availability()
    argv: list[str] = list(getattr(backend, "display_argv", ()))
    common: dict[str, Any] = {
        "checked_at_utc": checked,
        "checked_at_et": to_eastern(checked),
        "claude_version": availability.version,
        "prompt": PROBE_PROMPT,
        "env_added": dict(ADDED_ENV),
        "env_removed": list(STRIPPED_ENV),
        "model_requested": model_requested,
    }
    if not availability.available:
        report = ProbeReport(
            available=False,
            unavailable_reason=availability.reason,
            argv=argv,
            model_served=[],
            session_id=None,
            exit_code=None,
            duration_ms=None,
            is_error=None,
            backend_error=None,
            result_text=None,
            reply_is_ok=None,
            total_cost_usd=None,
            stdout_raw=None,
            stderr=None,
            **common,
        )
    else:
        reply = backend.complete(PROBE_PROMPT)
        report = ProbeReport(
            available=True,
            unavailable_reason=None,
            argv=list(reply.argv),
            model_served=list(reply.model_served),
            session_id=reply.session_id,
            exit_code=reply.exit_code,
            duration_ms=reply.duration_ms,
            is_error=reply.is_error,
            backend_error=reply.error,
            result_text=reply.result_text,
            reply_is_ok=(
                reply.result_text.strip() == "OK"
                if reply.result_text is not None
                else None
            ),
            total_cost_usd=reply.total_cost_usd,
            stdout_raw=reply.raw_stdout,
            stderr=reply.stderr,
            **common,
        )
    data_rel: str | None = None
    if writer is not None:
        data_rel = f"doctor/{format_run_id(checked)}.json"
        writer.write_json_atomic(data_rel, report.model_dump(mode="json"))
    return ProbeResult(report, data_rel)


__all__ = [
    "PROBE_PROMPT",
    "CliJudge",
    "JudgeAttempt",
    "JudgeRun",
    "ProbeReport",
    "ProbeResult",
    "build_backend",
    "build_judge",
    "judge_posting",
    "judge_posting_detailed",
    "probe_model",
]
