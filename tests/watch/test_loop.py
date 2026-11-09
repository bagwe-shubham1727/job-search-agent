"""The watch loop: exits, budgets, repeat rule, error policy and trace (GATE §2-5).

Every board response here is CONSTRUCTED in memory and served by an ``httpx`` mock
transport; the real provider, rule, résumé gate, pipeline and file writer run.
"""

from __future__ import annotations

import json
import shutil
from collections.abc import Callable
from datetime import timedelta
from pathlib import Path
from typing import Any

import httpx
import pytest

from job_search_agent.config import AgentConfig, load_config
from job_search_agent.events import EventLog
from job_search_agent.evidence_validator import validate_rule_evidence
from job_search_agent.fsio import ReadPolicy, create_output_root
from job_search_agent.http import build_fetcher_from_settings
from job_search_agent.models import FetchErrorKind, JudgmentStatus, RunReport, RunStatus
from job_search_agent.pipeline import RunDeps
from job_search_agent.providers import get_provider
from job_search_agent.resume import load_verified_resume
from job_search_agent.rule.verdict import evaluate
from job_search_agent.watch import (
    BoardOutcome,
    BoardState,
    Budget,
    BudgetMeter,
    LoopDeps,
    LoopExit,
    LoopFetcher,
    LoopReport,
    RetrySettings,
    WatchPlan,
    board_ok,
    build_policy,
    decide_exit,
    run_loop,
)
from tests.conftest import FIXED_START, REPO_ROOT, RESUME_FIXTURE_REL
from tests.fakes import FakeGit, FixedClock, RecordingTransport, mock_transport
from tests.tools.builders import job

GH = "https://boards-api.greenhouse.io/v1/boards/{}/jobs?content=true"
ASHBY = "https://api.ashbyhq.com/posting-api/job-board/{}"
UUID = "34413f8d-26bf-4bbc-8ade-eb309a0e2245"
UUID_NEW = "8fb1615c-34bf-47c4-a1d1-b7b2f836bbd3"

Handler = Callable[[httpx.Request], httpx.Response]


def gh_body(*ids: int) -> bytes:
    jobs = [job(id=i, content="&lt;p&gt;Java and Python on AWS&lt;/p&gt;") for i in ids]
    return json.dumps({"jobs": jobs, "meta": {"total": len(jobs)}}).encode()


def ashby_body(*ids: str) -> bytes:
    jobs = [
        {
            "id": i,
            "title": "Software Engineer",
            "location": "New York, NY",
            "department": "Engineering",
            "descriptionHtml": "<p>TypeScript, PostgreSQL and Docker</p>",
        }
        for i in ids
    ]
    return json.dumps({"jobs": jobs, "apiVersion": "1"}).encode()


def ok(body: bytes) -> Handler:
    return lambda _request: httpx.Response(200, content=body)


def status(code: int) -> Handler:
    return lambda _request: httpx.Response(code, content=b'{"error":"x"}')


def sequence(*handlers: Handler) -> Handler:
    """Serves the handlers in order, one per request; extra requests fail the test."""
    queue = list(handlers)

    def serve(request: httpx.Request) -> httpx.Response:
        assert queue, "more requests than the test expected"
        return queue.pop(0)(request)

    return serve


def timeout(request: httpx.Request) -> httpx.Response:
    raise httpx.ReadTimeout("constructed timeout", request=request)


class FakeTimer:
    """Seconds clock; tests advance it."""

    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now


class Project:
    """A temporary project: the fixture, agent config and a constructed plan."""

    def __init__(self, root: Path) -> None:
        self.root = root
        for rel in ("config/agent.toml", RESUME_FIXTURE_REL, "prompts/judge.v1.md"):
            (root / rel).parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(REPO_ROOT / rel, root / rel)
        self.config: AgentConfig = load_config(root / "config" / "agent.toml")
        self.clock = FixedClock(FIXED_START, step=timedelta(seconds=1))
        self.timer = FakeTimer()
        self.sleeps: list[float] = []
        self.transport: RecordingTransport | None = None

    def plan(
        self,
        boards: list[tuple[str, str]],
        *,
        max_boards: int = 6,
        max_requests: int = 10,
        max_seconds: float = 180,
        hosts: tuple[str, ...] = ("boards-api.greenhouse.io", "api.ashbyhq.com"),
    ) -> WatchPlan:
        return WatchPlan.model_validate(
            {
                "budget": {
                    "max_boards": max_boards,
                    "max_requests": max_requests,
                    "max_seconds": max_seconds,
                },
                "retry": {"max_retries": 1, "pause_s": 2.0, "min_seconds_left": 5.0},
                "policy": {"allowed_hosts": list(hosts), "write_root": "data/watch"},
                "boards": [{"provider": p, "token": t} for p, t in boards],
            }
        )

    def board_deps(self, cfg: AgentConfig) -> RunDeps:
        read = ReadPolicy(cfg.project_root).read_bytes

        def resume() -> Any:  # noqa: ANN401 - VerifiedResume
            return load_verified_resume(
                cfg.resume_path,
                cfg.resume.pinned_sha256,
                read_bytes=read,
                project_root=cfg.project_root,
            )

        return RunDeps(
            config=cfg,
            clock=self.clock,
            source=_NoSource(),
            provider=get_provider(cfg.board.provider),
            load_resume=resume,
            evaluate=evaluate,
            validate_evidence=validate_rule_evidence,
            judge=None,
            out=create_output_root(cfg.data_dir),
            git=FakeGit(),
            events=EventLog(),
            seeded=False,
            read_repo_file=lambda rel: read(cfg.project_root / rel),
        )

    def run(self, plan: WatchPlan, routes: dict[str, Handler]) -> LoopReport:
        self.transport = mock_transport(routes)
        deps = LoopDeps(
            plan=plan,
            base_config=self.config,
            policy=build_policy(plan, self.root),
            clock=self.clock,
            monotonic=self.timer,
            board_deps=self.board_deps,
            transport=self.transport,
            sleep=self.sleeps.append,
        )
        return run_loop(deps)

    def loop_dir(self, report: LoopReport) -> Path:
        return self.root / "data" / "watch" / "loops" / report.loop_id

    def trace(self, report: LoopReport) -> list[dict[str, Any]]:
        lines = (self.loop_dir(report) / "trace.jsonl").read_text().splitlines()
        return [json.loads(line) for line in lines]

    def state(self, board: str) -> Path:
        return self.root / "data/watch/boards" / board / "live/state.json"


class _NoSource:
    def obtain(self) -> Any:  # noqa: ANN401
        raise AssertionError("the loop must replace the board's source")


@pytest.fixture
def p(tmp_path: Path) -> Project:
    return Project(tmp_path / "project")


def _by_board(report: LoopReport) -> dict[str, BoardOutcome]:
    return {b.board: b for b in report.boards}


THREE = [("greenhouse", "stripe"), ("greenhouse", "figma"), ("ashby", "ramp")]


def three_ok() -> dict[str, Handler]:
    return {
        GH.format("stripe"): ok(gh_body(1, 2)),
        GH.format("figma"): ok(gh_body(3)),
        ASHBY.format("ramp"): ok(ashby_body(UUID)),
    }


# --- exits --------------------------------------------------------------------


def test_finished_when_every_board_is_ok(p: Project) -> None:
    report = p.run(p.plan(THREE), three_ok())
    assert report.exit is LoopExit.FINISHED
    boards = _by_board(report)
    assert [b.state for b in report.boards] == [BoardState.OK] * 3
    assert boards["greenhouse/stripe"].fetched_count == 2
    assert boards["ashby/ramp"].run_status is RunStatus.BASELINE
    assert report.requests_used == 3
    assert p.state("ashby-ramp").exists()
    loop_dir = p.loop_dir(report)
    assert json.loads((loop_dir / "report.json").read_text())["exit"] == "FINISHED"
    assert (
        "Nothing: every planned board was checked."
        in (loop_dir / "report.md").read_text()
    )


def test_trace_records_every_observation(p: Project) -> None:
    report = p.run(p.plan(THREE), three_ok())
    events = [e["event"] for e in p.trace(report)]
    assert events[0] == "loop.started"
    assert events[-1] == "loop.finished"
    for name in ("board.started", "tool.fetch.attempt", "tool.fetch.result"):
        assert events.count(name) == 3
    assert events.count("board.finished") == 3
    result = next(e for e in p.trace(report) if e["event"] == "tool.fetch.result")
    assert result["status_code"] == 200
    assert len(result["sha256"]) == 64


def test_bad_board_name_is_not_retried_and_loop_is_incomplete(p: Project) -> None:
    plan = p.plan([*THREE, ("ashby", "linearapp")])
    routes = {**three_ok(), ASHBY.format("linearapp"): status(404)}
    report = p.run(plan, routes)
    failed = _by_board(report)["ashby/linearapp"]
    assert report.exit is LoopExit.INCOMPLETE
    assert failed.state is BoardState.FAILED
    assert failed.run_status is RunStatus.FETCH_FAILED
    assert failed.http_status == 404
    assert failed.requests == 1
    assert (failed.fetched_count, failed.new_count, failed.pending_count) == (
        None,
        None,
        None,
    )
    assert not p.state("ashby-linearapp").exists()
    assert (
        "`ashby/linearapp`: FAILED FETCH_FAILED"
        in (p.loop_dir(report) / "report.md").read_text()
    )
    assert p.sleeps == []


def test_empty_board_is_failed_not_no_new_jobs(p: Project) -> None:
    plan = p.plan([("greenhouse", "stripe"), ("ashby", "vercel")])
    routes = {
        GH.format("stripe"): ok(gh_body(1)),
        ASHBY.format("vercel"): ok(b'{"jobs":[],"apiVersion":"1"}'),
    }
    report = p.run(plan, routes)
    empty = _by_board(report)["ashby/vercel"]
    assert empty.state is BoardState.FAILED
    assert empty.run_status is RunStatus.EMPTY_RESPONSE
    assert empty.new_count is None
    assert report.exit is LoopExit.INCOMPLETE


def test_every_board_failed_is_error(p: Project) -> None:
    plan = p.plan([("greenhouse", "stripe"), ("ashby", "ramp")])
    routes = {GH.format("stripe"): status(404), ASHBY.format("ramp"): status(403)}
    report = p.run(plan, routes)
    assert report.exit is LoopExit.ERROR


def test_corrupt_state_stops_the_loop_with_error(p: Project) -> None:
    state = p.state("greenhouse-figma")
    state.parent.mkdir(parents=True)
    state.write_text("not json")
    report = p.run(p.plan(THREE), three_ok())
    assert report.exit is LoopExit.ERROR
    assert report.reason == "StateCorrupt:greenhouse/figma"
    assert state.read_text() == "not json"
    assert [b.state for b in report.boards] == [
        BoardState.OK,
        BoardState.NOT_ATTEMPTED,
        BoardState.NOT_ATTEMPTED,
    ]


# --- error policy -------------------------------------------------------------


def test_timeout_is_retried_once_then_ok(p: Project) -> None:
    plan = p.plan([("greenhouse", "stripe")])
    report = p.run(plan, {GH.format("stripe"): sequence(timeout, ok(gh_body(1)))})
    (board,) = report.boards
    assert board.state is BoardState.OK
    assert board.requests == 2
    assert p.sleeps == [2.0]
    assert "tool.fetch.retry" in [e["event"] for e in p.trace(report)]


def test_5xx_twice_fails_after_one_retry(p: Project) -> None:
    plan = p.plan([("greenhouse", "stripe"), ("ashby", "ramp")])
    routes = {
        GH.format("stripe"): sequence(status(503), status(503)),
        ASHBY.format("ramp"): ok(ashby_body(UUID)),
    }
    report = p.run(plan, routes)
    failed = _by_board(report)["greenhouse/stripe"]
    assert failed.run_status is RunStatus.FETCH_FAILED
    assert failed.http_status == 503
    assert failed.requests == 2
    assert report.exit is LoopExit.INCOMPLETE


@pytest.mark.parametrize("code", [404, 429, 400])
def test_4xx_is_never_retried(p: Project, code: int) -> None:
    plan = p.plan([("greenhouse", "stripe"), ("ashby", "ramp")])
    routes = {
        GH.format("stripe"): sequence(status(code)),
        ASHBY.format("ramp"): ok(ashby_body(UUID)),
    }
    report = p.run(plan, routes)
    assert _by_board(report)["greenhouse/stripe"].requests == 1
    assert p.sleeps == []


def test_no_retry_when_time_is_nearly_up(p: Project) -> None:
    plan = p.plan([("greenhouse", "stripe")], max_seconds=10)

    def slow_failure(request: httpx.Request) -> httpx.Response:
        p.timer.now = 7.0
        return timeout(request)

    report = p.run(plan, {GH.format("stripe"): sequence(slow_failure)})
    assert report.boards[0].requests == 1
    assert "tool.fetch.retry_skipped" in [e["event"] for e in p.trace(report)]


def test_b07_redirect_off_the_allow_list_fails_the_board(p: Project) -> None:
    plan = p.plan([("greenhouse", "stripe"), ("ashby", "ramp")])
    redirect = httpx.Response(302, headers={"location": "https://evil.example/jobs"})
    routes = {
        GH.format("stripe"): lambda _r: redirect,
        ASHBY.format("ramp"): ok(ashby_body(UUID)),
    }
    report = p.run(plan, routes)
    failed = _by_board(report)["greenhouse/stripe"]
    assert failed.fetch_error is FetchErrorKind.REDIRECT_REJECTED
    assert failed.requests == 1
    assert p.transport is not None
    assert {r.url.host for r in p.transport.requests} == {
        "boards-api.greenhouse.io",
        "api.ashbyhq.com",
    }


# --- budgets ------------------------------------------------------------------


def test_request_budget_stops_before_the_next_board(p: Project) -> None:
    report = p.run(p.plan(THREE, max_requests=2), three_ok())
    assert report.exit is LoopExit.BUDGET_EXHAUSTED
    assert report.reason == "max_requests"
    assert report.requests_used == 2
    assert p.transport is not None
    assert len(p.transport.requests) == 2
    assert _by_board(report)["ashby/ramp"].state is BoardState.NOT_ATTEMPTED


def test_request_budget_also_bounds_a_retry(p: Project) -> None:
    plan = p.plan([("greenhouse", "stripe")], max_requests=1)
    report = p.run(plan, {GH.format("stripe"): sequence(status(503))})
    assert report.requests_used == 1
    assert report.boards[0].requests == 1


def test_board_budget(p: Project) -> None:
    report = p.run(p.plan(THREE, max_boards=2), three_ok())
    assert report.exit is LoopExit.BUDGET_EXHAUSTED
    assert report.reason == "max_boards"
    assert [b.state for b in report.boards][-1] is BoardState.NOT_ATTEMPTED


def test_time_budget(p: Project) -> None:
    def slow(request: httpx.Request) -> httpx.Response:
        p.timer.now = 200.0
        return ok(gh_body(1))(request)

    routes = {**three_ok(), GH.format("stripe"): slow}
    report = p.run(p.plan(THREE), routes)
    assert report.exit is LoopExit.BUDGET_EXHAUSTED
    assert report.reason == "max_seconds"
    assert report.boards[0].state is BoardState.OK
    assert {b.state for b in report.boards[1:]} == {BoardState.NOT_ATTEMPTED}


# --- repeat rule --------------------------------------------------------------


def test_same_board_in_other_case_is_fetched_once(p: Project) -> None:
    plan = p.plan([("greenhouse", "stripe"), ("Greenhouse", " Stripe ")])
    report = p.run(plan, {GH.format("stripe"): ok(gh_body(1))})
    assert [b.state for b in report.boards] == [
        BoardState.OK,
        BoardState.SKIPPED_REPEAT,
    ]
    assert report.exit is LoopExit.FINISHED
    assert p.transport is not None
    assert len(p.transport.requests) == 1


def test_b20_third_get_of_one_url_is_refused(p: Project) -> None:
    plan = p.plan([("greenhouse", "stripe")])
    policy = build_policy(plan, p.root)
    transport = mock_transport({GH.format("stripe"): ok(gh_body(1))})
    fetcher = LoopFetcher(
        policy=policy,
        meter=BudgetMeter(plan.budget, p.timer, 0.0),
        retry=RetrySettings(max_retries=1, pause_s=0, min_seconds_left=0),
        trace=EventLog(),
        board="greenhouse/stripe",
        build=lambda t, e: build_fetcher_from_settings(
            p.config.http, inner=transport, events=e
        ),
        board_events=EventLog(),
        timeout_cap=30,
    )
    url = GH.format("stripe")
    assert fetcher.get(url).ok
    assert fetcher.get(url).ok
    third = fetcher.get(url)
    assert third.error is FetchErrorKind.POLICY_REFUSED
    assert third.error_detail == "repeat"
    assert len(transport.requests) == 2


# --- the plan and the policy --------------------------------------------------


def test_plan_refused_by_policy_is_error_before_any_fetch(p: Project) -> None:
    plan = p.plan(THREE, hosts=("boards-api.greenhouse.io",))
    report = p.run(plan, three_ok())
    assert report.exit is LoopExit.ERROR
    assert report.reason == "plan_refused:ashby/ramp:host"
    assert report.requests_used == 0
    assert p.transport is not None
    assert p.transport.requests == []


def test_invalid_token_is_error_before_any_fetch(p: Project) -> None:
    report = p.run(p.plan([("greenhouse", "stripe"), ("ashby", "a/../b")]), {})
    assert report.exit is LoopExit.ERROR
    assert report.reason.startswith("plan_invalid:")


# --- second run: new postings, deferred judgments, untouched failed state ------


def test_second_run_new_postings_with_deferred_judgments_is_ok(p: Project) -> None:
    plan = p.plan([("greenhouse", "stripe"), ("ashby", "ramp")])
    p.run(
        plan,
        {
            GH.format("stripe"): ok(gh_body(1)),
            ASHBY.format("ramp"): ok(ashby_body(UUID)),
        },
    )
    second = p.run(
        plan,
        {
            GH.format("stripe"): ok(gh_body(1)),
            ASHBY.format("ramp"): ok(ashby_body(UUID, UUID_NEW)),
        },
    )
    ramp = _by_board(second)["ashby/ramp"]
    assert second.exit is LoopExit.FINISHED
    assert ramp.run_status is RunStatus.PARTIAL_FAILURE
    assert ramp.note == "judgments_deferred"
    assert (ramp.new_count, ramp.pending_count) == (1, 1)
    assert _by_board(second)["greenhouse/stripe"].run_status is RunStatus.SUCCESS_NO_NEW
    records_path = (
        p.root
        / "data/watch/boards/ashby-ramp"
        / (ramp.run_folder or "").split("ashby-ramp/", 1)[1]
        / "records.json"
    )
    records = json.loads(records_path.read_text())
    assert [r["posting_id"] for r in records] == [UUID_NEW]
    assert records[0]["rule_verdict"]["label"] == "MATCH"


def test_failed_board_leaves_saved_state_untouched(p: Project) -> None:
    plan = p.plan([("greenhouse", "stripe"), ("ashby", "ramp")])
    p.run(
        plan,
        {
            GH.format("stripe"): ok(gh_body(1)),
            ASHBY.format("ramp"): ok(ashby_body(UUID)),
        },
    )
    before = p.state("greenhouse-stripe").read_bytes()
    p.run(
        plan,
        {GH.format("stripe"): status(404), ASHBY.format("ramp"): ok(ashby_body(UUID))},
    )
    assert p.state("greenhouse-stripe").read_bytes() == before


# --- the GATE §2 rules as functions -------------------------------------------


def _o(state: BoardState) -> BoardOutcome:
    return BoardOutcome(board="x/y", state=state)


@pytest.mark.parametrize(
    ("states", "stopped_by", "expected"),
    [
        ([BoardState.OK, BoardState.OK], None, LoopExit.FINISHED),
        ([BoardState.OK, BoardState.SKIPPED_REPEAT], None, LoopExit.FINISHED),
        ([BoardState.OK, BoardState.FAILED], None, LoopExit.INCOMPLETE),
        ([BoardState.FAILED, BoardState.FAILED], None, LoopExit.ERROR),
        (
            [BoardState.OK, BoardState.NOT_ATTEMPTED],
            "max_boards",
            LoopExit.BUDGET_EXHAUSTED,
        ),
        (
            [BoardState.OK, BoardState.FAILED, BoardState.NOT_ATTEMPTED],
            "max_requests",
            LoopExit.BUDGET_EXHAUSTED,
        ),
        ([BoardState.FAILED, BoardState.NOT_ATTEMPTED], "max_seconds", LoopExit.ERROR),
        ([BoardState.SKIPPED_REPEAT], None, LoopExit.ERROR),
    ],
)
def test_decide_exit(
    states: list[BoardState], stopped_by: str | None, expected: LoopExit
) -> None:
    assert decide_exit([_o(s) for s in states], stopped_by=stopped_by) is expected


def _report(status: RunStatus, **fields: Any) -> RunReport:
    base: dict[str, Any] = {
        "run_id": "2026-11-09T08-00-00Z",
        "mode": "live",
        "seeded": False,
        "provider": "ashby",
        "board": "ramp",
        "code_commit": None,
        "code_dirty": None,
        "started_at_utc": FIXED_START,
        "started_at_et": FIXED_START,
        "finished_at_utc": FIXED_START,
        "finished_at_et": FIXED_START,
        "status": status,
        "fetched_count": 1,
        "unique_valid_ids": 1,
        "new_count": 0,
        "records_saved": True,
        "state_saved": True,
        "model_backend": "none",
    }
    base.update(fields)
    return RunReport.model_validate(base)


def test_board_ok_rules() -> None:
    deferred = _report(
        RunStatus.PARTIAL_FAILURE,
        notes=["judgments_not_valid", "pending_unresolved", "judge_unavailable"],
        judgment_counts={JudgmentStatus.UNAVAILABLE: 2},
    )
    assert board_ok(deferred) == (True, "judgments_deferred")
    with_errors = deferred.model_copy(
        update={"notes": [*deferred.notes, "data_quality_errors"]}
    )
    assert board_ok(with_errors)[0] is False
    real_model = deferred.model_copy(update={"model_backend": "claude-cli"})
    assert board_ok(real_model)[0] is False
    invalid = deferred.model_copy(
        update={"judgment_counts": {JudgmentStatus.INVALID_OUTPUT: 1}}
    )
    assert board_ok(invalid)[0] is False
    for failed in (RunStatus.EMPTY_RESPONSE, RunStatus.FETCH_FAILED):
        assert board_ok(_report(failed))[0] is False
    assert board_ok(_report(RunStatus.SUCCESS_NO_NEW)) == (True, "SUCCESS_NO_NEW")


def test_budget_values_are_validated() -> None:
    with pytest.raises(ValueError, match="max_boards"):
        Budget(max_boards=0, max_requests=1, max_seconds=1)
