"""Sampling report harness (PLAN §6.1)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from job_search_agent.experiments import sampling
from job_search_agent.experiments._calls import CallRecord
from job_search_agent.experiments._io import ExperimentError
from job_search_agent.experiments.selection import HANDCHECK_IDS
from job_search_agent.models import BackendErrorKind, JudgmentStatus, VerdictLabel
from tests.experiments.helpers import Repo, first_reply_judge, make_repo, reply_text
from tests.judge.doubles import REPO_ROOT, handcheck_posting

POSTINGS = {pid: handcheck_posting(pid) for pid in HANDCHECK_IDS}


def _run(repo: Repo, script: list[Any], n: int = 2) -> tuple[dict[str, Any], Any]:
    judge, backend = first_reply_judge(repo, script)
    manifest = sampling.cmd_sampling_run(
        repo.ctx,
        n=n,
        postings=POSTINGS,
        prompt=repo.load_prompt("v1"),
        judge_call=judge,
        model_requested="claude-sonnet-5-5",
    )
    return manifest, backend


def test_call_order_round_robin() -> None:
    order = sampling.call_order(2)
    assert order[:5] == [(1, pid) for pid in HANDCHECK_IDS]
    assert order[5:] == [(2, pid) for pid in HANDCHECK_IDS]


def test_sampling_first_reply_no_retry(tmp_path: Path) -> None:
    repo = make_repo(tmp_path)
    script: list[Any] = ["```json\n{}\n```"] * 5 + [reply_text()] * 5
    manifest, backend = _run(repo, script)
    assert backend.calls == 10  # an invalid first reply is never retried
    calls = [c["call"] for c in manifest["calls"]]
    assert [c["first_reply_valid"] for c in calls] == [False] * 5 + [True] * 5
    assert all(c["status"] == "INVALID_OUTPUT" for c in calls[:5])
    first = calls[0]
    assert (
        first["raw_log_ref"]
        == "data/experiments/sampling/calls/8249901/1/attempt-1.json"
    )
    log = repo.data("experiments/sampling/calls/8249901/1/attempt-1.json")
    assert log["first_reply"] is True and log["session_id"] == first["session_id"]
    assert manifest["prompt_sha256"] == repo.load_prompt("v1").sha256
    with pytest.raises(ExperimentError, match="already run"):
        _run(repo, [])


def test_sampling_refuses_non_v1_prompt(tmp_path: Path) -> None:
    repo = make_repo(tmp_path)
    repo.write(
        "prompts/judge.v2.md", (REPO_ROOT / "prompts/judge.v1.md").read_text("utf-8")
    )
    judge, _ = first_reply_judge(repo, [])
    with pytest.raises(ExperimentError, match="v1 only"):
        sampling.cmd_sampling_run(
            repo.ctx,
            n=1,
            postings=POSTINGS,
            prompt=repo.load_prompt("v2"),
            judge_call=judge,
            model_requested=None,
        )


def _record(
    pid: str,
    session: str | None,
    label: str | None = "RELEVANT",
    paths: list[list[str]] | None = None,
) -> CallRecord:
    return CallRecord(
        posting_id=pid,
        status=JudgmentStatus.VALID if label else JudgmentStatus.INVALID_OUTPUT,
        first_reply_valid=label is not None,
        validation_codes=[] if label else ["NOT_JSON"],
        label=label,  # type: ignore[arg-type]
        evidence_paths=paths
        if paths is not None
        else [["$.skills.languages[2]", "$.content"]],
        parseable=label is not None,
        path_entries=1,
        path_entries_valid=1,
        session_id=session,
        model_served=["claude-sonnet-5-5"],
        raw_log_ref=None,
        started_at_utc=None,
        started_at_et=None,
        prompt_id="judge.v1",
        prompt_sha256="0" * 64,
    )


def test_sampling_session_ids_distinct() -> None:
    assert (
        sampling.check_distinct_sessions(
            [_record("1", "a"), _record("1", "b"), _record("1", None)]
        )
        == 1
    )
    with pytest.raises(ExperimentError, match="repeat"):
        sampling.check_distinct_sessions([_record("1", "a"), _record("2", "a")])


def test_table_refuses_on_repeated_session(tmp_path: Path) -> None:
    repo = make_repo(tmp_path)
    manifest, _ = _run(repo, [reply_text()] * 10)
    manifest["calls"][1]["call"]["session_id"] = manifest["calls"][0]["call"][
        "session_id"
    ]
    repo.writer.write_json_atomic(sampling.MANIFEST, manifest)
    with pytest.raises(ExperimentError, match="refusing to report"):
        sampling.cmd_sampling_table(repo.ctx)


def test_spread_table() -> None:
    hand = {pid: VerdictLabel.NO_MATCH for pid in HANDCHECK_IDS}
    hand["8249901"] = VerdictLabel.MATCH
    calls = [
        _record("8249901", "s1", "RELEVANT"),
        _record("8249901", "s2", "RELEVANT", [["$.skills.backend[0]", "$.title"]]),
        _record("8249901", "s3", None),
        _record("7543868", "s4", "RELEVANT"),
        _record("7543868", "s5", "RELEVANT"),
    ]
    rows = {r.posting_id: r for r in sampling.spread_table(calls, hand)}
    first = rows["8249901"]
    assert (first.n, first.relevant, first.not_relevant, first.invalid) == (3, 2, 0, 1)
    assert first.modal_outcome == "MATCH" and not first.unanimous
    assert (first.agreement_with_hand.k, first.agreement_with_hand.n) == (2, 3)
    assert first.distinct_evidence_path_sets == 2
    assert (first.format_acceptance.k, first.format_acceptance.n) == (2, 3)
    second = rows["7543868"]
    assert second.unanimous and second.unanimous_and_wrong
    assert second.agreement_with_hand.k == 0
    assert set(rows) == {"8249901", "7543868"}


def test_table_writes_spread_and_student_conclusion(tmp_path: Path) -> None:
    repo = make_repo(tmp_path)
    script: list[Any] = (
        [reply_text("NOT_RELEVANT")] * 4
        + [BackendErrorKind.TIMEOUT]
        + [reply_text("NOT_RELEVANT")] * 5
    )
    _run(repo, script)
    doc = sampling.cmd_sampling_table(repo.ctx)
    assert doc["session_ids_distinct"] is True
    assert doc["hand_labels_confirmed_by_student"] is None
    rows = {r["posting_id"]: r for r in doc["rows"]}
    assert rows["8249901"]["unanimous_and_wrong"] is True
    assert rows["8234357"]["invalid"] == 1  # the timed-out call
    text = (repo.root / "data/experiments/sampling/SAMPLING.tables.md").read_text(
        "utf-8"
    )
    assert "Repeatable is not correct" in text
    assert "unanimous and wrong" in text
    assert "## Conclusion\n\n<!-- STUDENT WRITES THIS -->" in text
    assert "not yet confirmed by the student" in text


def test_hand_labels_scaffold_matches_contract_section_13() -> None:
    doc = json.loads(
        (REPO_ROOT / "experiments/sampling/hand_labels.json").read_text("utf-8")
    )
    assert doc["source"] == "CONTRACT.md §13"
    assert doc["confirmed_by_student"] is None
    labels = {pid: v["hand_label"] for pid, v in doc["labels"].items()}
    assert labels == {
        "8249901": "MATCH",
        "7543868": "NO_MATCH",
        "8175099": "NO_MATCH",
        "8127182": "NO_MATCH",
        "8234357": "NO_MATCH",
    }
