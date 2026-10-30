"""Action-surface harness (PLAN §6.3, R2); no real process or network."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from job_search_agent.experiments import surfaces
from job_search_agent.experiments._io import ExperimentError
from job_search_agent.judge.payload import build_posting_payload, build_resume_payload
from job_search_agent.models import CompletedCommand, FetchResult
from tests.experiments.helpers import Repo, make_repo, reply_text
from tests.fakes import FakeRunner
from tests.judge.doubles import handcheck_posting, make_resume, simple_clean

MODEL = "claude-sonnet-5-5"
SNAPSHOT = {
    "head": "a" * 40,
    "status_porcelain": [],
    "tracked_files": 3,
    "tracked_sha256": "b" * 64,
}


@pytest.mark.parametrize("surface", surfaces.SURFACES)
def test_surfaces_argv_never_bypass(surface: str) -> None:
    argv = surfaces.surface_argv(surface, "claude", MODEL)
    joined = " ".join(argv)
    for forbidden in (
        "--dangerously-skip-permissions",
        "bypassPermissions",
        "--bare",
        "Bash",
    ):
        assert forbidden not in joined
    assert argv[argv.index("--setting-sources") + 1] == "project"
    assert "--safe-mode" in argv and "--no-session-persistence" in argv
    assert "--strict-mcp-config" in argv
    assert argv[argv.index("--output-format") + 1] == "stream-json"
    assert argv[argv.index("--max-budget-usd") + 1] == "0.50"
    assert argv[argv.index("--model") + 1] == MODEL


def test_surface_specific_permissions() -> None:
    a = surfaces.surface_argv("a", "claude", MODEL)
    assert a[a.index("--tools") + 1] == ""
    b = surfaces.surface_argv("b", "claude", MODEL)
    assert b[b.index("--tools") + 1] == "Read"
    assert "Read(./posting.json)" in b and "Read(./resume.payload.json)" in b
    assert b[b.index("--permission-mode") + 1] == "dontAsk"
    c = surfaces.surface_argv("c", "claude", MODEL)
    assert c[c.index("--tools") + 1] == "WebFetch,Read,Edit,Write"
    assert "WebFetch(domain:boards-api.greenhouse.io)" in c
    assert "Edit(./state.json)" in c  # R2: write permission is an Edit rule
    assert not any(arg.startswith("Write(") for arg in c)
    assert c[c.index("--permission-mode") + 1] == "dontAsk"
    with pytest.raises(ExperimentError):
        surfaces.surface_argv("d", "claude", MODEL)


def test_surfaces_tree_snapshot_detects_change(tmp_path: Path) -> None:
    root = tmp_path / "sandbox"
    root.mkdir()
    (root / "state.json").write_text("{}")
    (root / "keep.txt").write_text("same")
    before = surfaces.tree_snapshot(root)
    assert before["state.json"]["sha256"] is not None
    (root / "state.json").write_text('{"seen_ids": []}')
    (root / "new.txt").write_text("x")
    (root / "keep.txt").unlink()
    (root / "link").symlink_to(root / "new.txt")
    after = surfaces.tree_snapshot(root)
    assert after["link"]["is_symlink"] is True and after["link"]["sha256"] is None
    assert surfaces.tree_diff(before, after) == {
        "added": ["link", "new.txt"],
        "removed": ["keep.txt"],
        "changed": ["state.json"],
    }
    assert surfaces.tree_diff(after, after) == {
        "added": [],
        "removed": [],
        "changed": [],
    }


def test_id_diff() -> None:
    result = surfaces.id_diff(
        ["1", "2"], {"2", "3", "4"}, {"seen_ids": ["1", "2", "3", 5, "x7", True]}
    )
    assert result["missing"] == ["4"]
    assert result["extra"] == ["5"]
    assert result["malformed"] == ["x7", "True"]
    assert result["added_by_agent"] == ["3", "5"]
    assert result["truly_new"] == ["3", "4"]
    assert surfaces.id_diff(["1"], {"1"}, None)["state_readable"] is False


def _stream(
    sandbox: str, *, result: str = "done", tools: list[dict[str, Any]] | None = None
) -> str:
    events: list[dict[str, Any]] = [
        {"type": "system", "subtype": "init", "model": MODEL},
        {
            "type": "assistant",
            "message": {
                "content": [
                    {"type": "tool_use", "name": t["name"], "input": t["input"]}
                    for t in tools or []
                ]
            },
        },
        {
            "type": "result",
            "result": result,
            "session_id": "s-1",
            "is_error": False,
            "permission_denials": [
                {
                    "tool_name": "Read",
                    "tool_input": {"file_path": "/home/tester/.ssh/id_rsa"},
                }
            ],
        },
    ]
    return "\n".join(json.dumps(e) for e in events) + "\nnot json\n"


def test_parse_transcript_scrubs_paths() -> None:
    text = _stream(
        "/abs/sandbox",
        tools=[
            {"name": "Read", "input": {"file_path": "/abs/sandbox/state.json"}},
            {
                "name": "WebFetch",
                "input": {"url": surfaces.BOARD_URL_NO_CONTENT, "prompt": "list ids"},
            },
            {
                "name": "Edit",
                "input": {"file_path": "/abs/sandbox/state.json", "old_string": "x"},
            },
        ],
    )
    observed = surfaces.parse_transcript(
        text, sandbox="/abs/sandbox", home="/home/tester"
    )
    assert observed["reads"] == ["<sandbox>/state.json"]
    assert observed["writes"] == ["<sandbox>/state.json"]
    assert observed["sends"] == [surfaces.BOARD_URL_NO_CONTENT]
    assert observed["permission_denials"] == [
        {"tool_name": "Read", "input": {"file_path": "~/.ssh/id_rsa"}}
    ]
    assert observed["model"] == MODEL and observed["session_id"] == "s-1"
    assert observed["unparsed_lines"] == 1
    assert "old_string" not in json.dumps(observed)


class _Fetcher:
    def __init__(self, ids: list[int]) -> None:
        self.ids = ids
        self.urls: list[str] = []

    def get(self, url: str) -> FetchResult:
        self.urls.append(url)
        body = json.dumps(
            {"jobs": [{"id": i} for i in self.ids], "meta": {"total": len(self.ids)}}
        ).encode()
        return FetchResult(url, url, (), 200, {}, body, None)


def _prepare(repo: Repo) -> dict[str, Any]:
    return surfaces.cmd_prepare(
        repo.ctx,
        prompt=repo.load_prompt("v1"),
        resume_payload=build_resume_payload(make_resume()),
        posting_payload=build_posting_payload(
            handcheck_posting("8249901"), clean=simple_clean
        ),
        state_ids=["101", "102"],
        model_id=MODEL,
        executable="claude",
        repo_snapshot=lambda: dict(SNAPSHOT),
    )


def _done(stdout: str) -> CompletedCommand:
    return CompletedCommand((), 0, stdout, "", False, 1234)


def _run(
    repo: Repo, surface: str, runner: FakeRunner, fetcher: Any = None
) -> dict[str, Any]:
    return surfaces.cmd_run(
        repo.ctx,
        surface=surface,
        runner=runner,
        resolve_dir=repo.writer.resolve_for_write,
        executable="claude",
        which=lambda name: "/opt/bin/claude",
        base_env={
            "PATH": "/bin",
            "ANTHROPIC_API_KEY": "sk-ant-secret",
            "HOME": "/home/tester",
        },
        fetcher=fetcher,
    )


def test_prepare_run_capture_end_to_end(tmp_path: Path) -> None:
    repo = make_repo(tmp_path)
    prepared = _prepare(repo)
    assert set(prepared["surfaces"]) == {"a", "b", "c"}
    sandbox_a = repo.writer.resolve_for_write("experiments/surfaces/a/sandbox")
    sandbox_b = repo.writer.resolve_for_write("experiments/surfaces/b/sandbox")
    sandbox_c = repo.writer.resolve_for_write("experiments/surfaces/c/sandbox")
    assert list(sandbox_a.iterdir()) == []
    assert sorted(p.name for p in sandbox_b.iterdir()) == [
        "posting.json",
        "resume.payload.json",
    ]
    assert json.loads((sandbox_c / "state.json").read_text()) == {
        "seen_ids": ["101", "102"]
    }
    assert "absolute_url" not in (sandbox_b / "posting.json").read_text()
    with pytest.raises(ExperimentError, match="already prepared"):
        _prepare(repo)

    runner = FakeRunner(
        [
            _done(_stream(str(sandbox_a), result=reply_text())),
            _done(_stream(str(sandbox_b))),
            _done(_stream(str(sandbox_c))),
        ]
    )
    run_a = _run(repo, "a", runner)
    call = runner.calls[0]
    assert call.argv[0] == "/opt/bin/claude"
    assert call.argv[1:] == surfaces.surface_argv("a", "claude", MODEL)[1:]
    assert call.cwd == sandbox_a
    assert "ANTHROPIC_API_KEY" not in call.env
    assert call.env["CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC"] == "1"
    assert call.stdin.startswith("You are giving an opinion")
    assert run_a["argv"][0] == "claude"  # no absolute path recorded
    assert "ANTHROPIC_API_KEY" in run_a["env_removed"]
    with pytest.raises(ExperimentError, match="already run"):
        _run(repo, "a", runner)
    _run(repo, "b", runner)
    with pytest.raises(ExperimentError, match="fetcher"):
        _run(repo, "c", runner)
    # The agent "adds" ID 103 but misses 104.
    (sandbox_c / "state.json").write_text(
        json.dumps({"seen_ids": ["101", "102", "103"]})
    )
    fetcher = _Fetcher([102, 103, 104])
    run_c = _run(repo, "c", runner, fetcher)
    assert fetcher.urls == [surfaces.BOARD_URL_NO_CONTENT]
    assert run_c["independent_check"]["http_status"] == 200

    captured = surfaces.cmd_capture(
        repo.ctx,
        resolve_dir=repo.writer.resolve_for_write,
        repo_snapshot=lambda: dict(SNAPSHOT),
        home="/home/tester",
    )
    assert captured["a"]["reply_validation"] == {"passed": True, "codes": []}
    assert captured["a"]["sandbox_changed"] is False
    assert captured["b"]["reply_validation"]["passed"] is False
    assert captured["c"]["sandbox_changed"] is True
    check = captured["c"]["independent_check"]
    assert (
        check["missing"] == ["104"]
        and check["extra"] == []
        and check["truly_new"] == ["103", "104"]
    )
    assert all(f["repo_unchanged"] for f in captured.values())
    assert captured["a"]["what_could_go_wrong"] is None
    tables = (
        repo.root / "data/experiments/surfaces/ACTION_SURFACES.tables.md"
    ).read_text()
    assert "## Least autonomy that suffices\n\n<!-- STUDENT WRITES THIS -->" in tables
    dumped = json.dumps(repo.writer.json)
    assert "sk-ant-secret" not in dumped
    assert str(tmp_path) not in json.dumps(
        {k: v for k, v in repo.writer.json.items() if "tree" not in k}
    )
    with pytest.raises(ExperimentError, match="already captured"):
        surfaces.cmd_capture(
            repo.ctx,
            resolve_dir=repo.writer.resolve_for_write,
            repo_snapshot=lambda: dict(SNAPSHOT),
            home="/home/tester",
            surfaces=("a",),
        )


def test_capture_detects_repo_change(tmp_path: Path) -> None:
    repo = make_repo(tmp_path)
    _prepare(repo)
    sandbox = repo.writer.resolve_for_write("experiments/surfaces/a/sandbox")
    _run(repo, "a", FakeRunner([_done(_stream(str(sandbox)))]))
    changed = dict(SNAPSHOT, status_porcelain=[" M src/x.py"])
    captured = surfaces.cmd_capture(
        repo.ctx,
        resolve_dir=repo.writer.resolve_for_write,
        repo_snapshot=lambda: changed,
        home="/h",
    )
    assert captured["a"]["repo_unchanged"] is False


def test_dry_run_makes_no_call(tmp_path: Path) -> None:
    repo = make_repo(tmp_path)
    _prepare(repo)
    runner = FakeRunner()
    result = surfaces.cmd_run(
        repo.ctx,
        surface="c",
        runner=runner,
        resolve_dir=repo.writer.resolve_for_write,
        executable="claude",
        which=lambda name: None,
        base_env={"ANTHROPIC_API_KEY": "k"},
        fetcher=None,
        dry_run=True,
    )
    assert runner.calls == []
    assert result["env_removed"] == ["ANTHROPIC_API_KEY"]
    assert "Edit(./state.json)" in result["argv"]


def test_git_repo_snapshot_excludes_own_outputs(tmp_path: Path) -> None:
    (tmp_path / "a.txt").write_text("x")
    runner = FakeRunner(
        [_done("abc\n"), _done(" M a.txt\n"), _done("a.txt\0gone.txt\0")]
    )
    snap = surfaces.git_repo_snapshot(runner, tmp_path, {"PATH": "/bin"})
    assert snap["head"] == "abc"
    assert snap["status_porcelain"] == [" M a.txt"]
    assert snap["tracked_files"] == 2
    status_argv = runner.calls[1].argv
    assert status_argv[:2] == ("git", "status")
    assert ":(exclude)data/experiments/surfaces" in status_argv
