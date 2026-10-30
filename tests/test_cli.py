"""``jsa`` CLI: parser, exit codes, offline commands (PLAN §1.4, §1.5, §3.4).

Components owned by other workstreams are replaced through the CLI's component
builders (``_load_resume``, ``_output_root``, ``_reader``, ``_provider``,
``_rule_functions``, ``build_run_deps``) with WS3-local doubles; the real wiring is
exercised in ``tests/test_integration.py``.
"""

from __future__ import annotations

import argparse
import json
import shutil
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

from job_search_agent import cli
from job_search_agent.config import AgentConfig, ConfigOverrides, load_config
from job_search_agent.errors import ConfigError, ResumeRefused
from job_search_agent.fsio import OutputRoot, create_output_root
from job_search_agent.models import (
    CompletedCommand,
    ExitCode,
    RefusalCode,
    RunStatus,
    VerifiedResume,
    exit_code_for_status,
)
from job_search_agent.pipeline import RunDeps
from job_search_agent.privacy import Finding, FindingKind
from job_search_agent.sources import LiveSource, ReplaySource
from job_search_agent.state import parse_state
from tests.conftest import HANDCHECK_META_REL, HANDCHECK_RAW_REL, REPO_ROOT
from tests.fakes import FakeBackend, FakeRunner, Reply
from tests.ws3_doubles import (
    CONSTRUCTED_ID,
    VALID_REPLY,
    FailingFetcher,
    Harness,
    LocalOutputRoot,
    StubProvider,
    constructed_with_added_posting,
    fixture_resume,
    handcheck_body,
    sensitive_resume_values,
    stub_evaluate,
    stub_validate,
)
from tests.ws3_doubles import JOBS_URL as URL

COMMANDS = ("run", "doctor", "pending", "rule", "verify-evidence", "audit-privacy")


def make_project(root: Path) -> Path:
    """Copies the config, .gitignore and evidence into a temporary project."""
    for rel in (
        "config/agent.toml",
        ".gitignore",
        HANDCHECK_RAW_REL,
        HANDCHECK_META_REL,
        "persona/kiran-joshi.resume.example.json",
    ):
        (root / rel).parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(REPO_ROOT / rel, root / rel)
    return root / "config" / "agent.toml"


@pytest.fixture
def project(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    config = make_project(tmp_path)
    monkeypatch.setattr(cli, "_load_resume", lambda cfg: fixture_resume())
    monkeypatch.setattr(cli, "_output_root", lambda cfg: LocalOutputRoot(cfg.data_dir))
    monkeypatch.setattr(cli, "_reader", lambda cfg: Path.read_bytes)
    monkeypatch.setattr(cli, "_provider", lambda cfg: StubProvider())
    monkeypatch.setattr(cli, "_rule_functions", lambda: (stub_evaluate, stub_validate))
    return config


def jsa(config: Path, *argv: str) -> int:
    return cli.main(["--config", str(config), *argv])


# --- parser ---------------------------------------------------------------------


def test_help(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as exit_info:
        cli.main(["--help"])
    assert exit_info.value.code == 0
    out = capsys.readouterr().out
    for command in COMMANDS:
        assert command in out


def test_run_help_lists_replay_and_backend(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit):
        cli.main(["run", "--help"])
    out = capsys.readouterr().out
    assert "--replay" in out and "--model-backend" in out


# --- run and exit codes ---------------------------------------------------------


def harness_builder(
    h: Harness, make: Callable[[Harness], RunDeps]
) -> Callable[[AgentConfig, Path | None], RunDeps]:
    def build(cfg: AgentConfig, replay: Path | None) -> RunDeps:
        return make(h)

    return build


def baseline_then(h: Harness) -> None:
    from job_search_agent.pipeline import run_once

    run_once(h.deps(h.live_source(Reply(body=handcheck_body()))))


def refuse() -> VerifiedResume:
    raise ResumeRefused([RefusalCode.EMAIL_DOMAIN])


ADDED = constructed_with_added_posting(handcheck_body(), title="Software Engineer, C")

SCENARIOS: dict[str, tuple[Callable[[Harness], RunDeps], bool, ExitCode]] = {
    "baseline": (
        lambda h: h.deps(h.live_source(Reply(body=handcheck_body()))),
        False,
        ExitCode.OK,
    ),
    "no_new": (
        lambda h: h.deps(h.live_source(Reply(body=handcheck_body()))),
        True,
        ExitCode.OK,
    ),
    "with_new": (lambda h: h.deps(h.live_source(Reply(body=ADDED))), True, ExitCode.OK),
    "partial": (
        lambda h: h.deps(h.live_source(Reply(body=ADDED)), use_judge=False),
        True,
        ExitCode.PARTIAL_FAILURE,
    ),
    "fetch_failed": (
        lambda h: h.deps(LiveSource(FailingFetcher(), URL)),
        True,
        ExitCode.FETCH_OR_RESPONSE,
    ),
    "empty": (
        lambda h: h.deps(
            h.live_source(Reply(body=b'{"jobs": [], "meta": {"total": 0}}'))
        ),
        True,
        ExitCode.FETCH_OR_RESPONSE,
    ),
    "invalid": (
        lambda h: h.deps(h.live_source(Reply(body=b"oops"))),
        True,
        ExitCode.FETCH_OR_RESPONSE,
    ),
    "resume_refused": (
        lambda h: h.deps(
            h.live_source(Reply(body=handcheck_body())), load_resume=refuse
        ),
        False,
        ExitCode.RESUME_REFUSED,
    ),
}


@pytest.mark.parametrize("scenario", sorted(SCENARIOS))
def test_exit_codes_map_statuses(
    scenario: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    make, with_baseline, expected = SCENARIOS[scenario]
    config = make_project(tmp_path)
    h = Harness.create(tmp_path, backend=FakeBackend([VALID_REPLY]))
    if with_baseline:
        baseline_then(h)
    monkeypatch.setattr(cli, "build_run_deps", harness_builder(h, make))
    assert jsa(config, "run") == int(expected)


def test_exit_code_for_corrupt_state(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config = make_project(tmp_path)
    h = Harness.create(tmp_path)
    state = h.data("live/state.json")
    state.parent.mkdir(parents=True)
    state.write_text("{}")
    make = SCENARIOS["baseline"][0]
    monkeypatch.setattr(cli, "build_run_deps", harness_builder(h, make))
    assert jsa(config, "run") == int(ExitCode.STATE_CORRUPT)


def test_exit_code_for_config_error(tmp_path: Path) -> None:
    assert jsa(tmp_path / "missing.toml", "run") == int(ExitCode.CONFIG_ERROR)


def test_every_status_has_an_exit_code() -> None:
    expected = {
        RunStatus.BASELINE: 0,
        RunStatus.SUCCESS_WITH_NEW: 0,
        RunStatus.SUCCESS_NO_NEW: 0,
        RunStatus.PARTIAL_FAILURE: 1,
        RunStatus.FETCH_FAILED: 2,
        RunStatus.EMPTY_RESPONSE: 2,
        RunStatus.INVALID_RESPONSE: 2,
    }
    assert {s: int(exit_code_for_status(s)) for s in RunStatus} == expected


def test_model_backend_none_override_reaches_config(
    project: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    seen: dict[str, Any] = {}

    def build(cfg: AgentConfig, replay: Path | None) -> RunDeps:
        seen["backend"] = cfg.model.backend
        seen["replay"] = replay
        raise ConfigError("stop here")

    monkeypatch.setattr(cli, "build_run_deps", build)
    assert jsa(project, "run", "--model-backend", "none") == int(ExitCode.CONFIG_ERROR)
    assert seen == {"backend": "none", "replay": None}


def test_build_run_deps_backend_none_is_honest_unavailable(project: Path) -> None:
    cfg = load_config(project, overrides=ConfigOverrides(model_backend="none"))
    deps = cli.build_run_deps(cfg, project.parent.parent / HANDCHECK_RAW_REL)
    assert deps.judge is None and deps.unavailable_reason == "backend_none"


def test_build_run_deps_real_judge_has_no_unavailable_reason(project: Path) -> None:
    root = project.parent.parent
    (root / "prompts").mkdir()
    shutil.copyfile(REPO_ROOT / "prompts/judge.v1.md", root / "prompts/judge.v1.md")
    cfg = load_config(project, overrides=ConfigOverrides(model_backend="claude-cli"))
    deps = cli.build_run_deps(cfg, root / HANDCHECK_RAW_REL, runner=FakeRunner())
    assert deps.judge is not None
    assert deps.unavailable_reason is None


def test_build_run_deps_replay_is_seeded_and_never_live(
    project: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        cli, "_fetcher", lambda cfg, events: pytest.fail("fetcher built")
    )
    cfg = load_config(project, overrides=ConfigOverrides(model_backend="none"))
    deps = cli.build_run_deps(cfg, project.parent.parent / HANDCHECK_RAW_REL)
    assert deps.seeded is True
    assert isinstance(deps.source, ReplaySource)
    assert deps.judge is None and deps.unavailable_reason == "backend_none"
    result = deps.source.obtain()
    assert result.ok and result.replayed_from is not None
    assert result.replayed_from.path == HANDCHECK_RAW_REL


def test_replay_outside_project_refused(
    project: Path, tmp_path_factory: pytest.TempPathFactory
) -> None:
    outside = tmp_path_factory.mktemp("outside") / "raw.json"
    outside.write_text("{}")
    cfg = load_config(project)
    with pytest.raises(ConfigError):
        cli.build_run_deps(cfg, outside)


def test_cli_run_end_to_end_with_doubles(
    project: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(cli, "SubprocessGit", lambda root, runner: _NoGit())
    code = jsa(
        project,
        "run",
        "--replay",
        str(project.parent.parent / HANDCHECK_RAW_REL),
        "--model-backend",
        "none",
    )
    out = capsys.readouterr().out
    assert code == 0
    assert out.startswith("> SEEDED RUN")
    assert "BASELINE" in out
    data = project.parent.parent / "data"
    assert (data / "seeded" / "state.json").exists()
    assert not (data / "live").exists()


class _NoGit:
    def head(self) -> str:
        raise RuntimeError("no git")

    def is_dirty(self) -> bool:
        raise RuntimeError("no git")

    def is_tracked_and_clean(self, path: Path) -> bool:
        return False


# --- doctor ---------------------------------------------------------------------


def test_doctor_offline_prints_no_resume_values(
    project: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(shutil, "which", lambda name: None)
    assert jsa(project, "doctor") == 0
    out = capsys.readouterr().out
    for value in sensitive_resume_values():
        assert value not in out
    assert "Kiran" not in out
    assert str(project.parent.parent) not in out
    for name in ("python", "claude", "resume", "gitignore", "allow-list", "data dir"):
        assert f"] {name}:" in out
    assert "boards-api.greenhouse.io" in out


def test_doctor_reports_claude_version_without_path(
    project: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(shutil, "which", lambda name: "/opt/secret/bin/claude")
    runner = FakeRunner(
        [CompletedCommand((), 0, "2.1.312 (Claude Code)\n", "", False, 3)]
    )
    cfg = load_config(project)
    checks = {c.name: c for c in cli.doctor_checks(cfg, runner)}
    assert checks["claude"].level == "OK"
    assert "2.1.312" in checks["claude"].detail
    assert "/opt/secret" not in checks["claude"].detail
    assert runner.calls[0].argv[1:] == ("--version",)
    assert "ANTHROPIC_API_KEY" not in runner.calls[0].env


def test_doctor_resume_refusal_exit_3(
    project: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    def refused(cfg: AgentConfig) -> VerifiedResume:
        raise ResumeRefused([RefusalCode.DIGEST_MISMATCH])

    monkeypatch.setattr(cli, "_load_resume", refused)
    monkeypatch.setattr(shutil, "which", lambda name: None)
    assert jsa(project, "doctor") == int(ExitCode.RESUME_REFUSED)
    assert "DIGEST_MISMATCH" in capsys.readouterr().out


def test_doctor_resume_config_error_is_exit_5(
    project: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def outside(cfg: AgentConfig) -> VerifiedResume:
        raise ConfigError("résumé path is outside the project root")

    monkeypatch.setattr(cli, "_load_resume", outside)
    monkeypatch.setattr(shutil, "which", lambda name: None)
    assert jsa(project, "doctor") == int(ExitCode.CONFIG_ERROR)


def test_doctor_gitignore_missing_rule_fails(
    project: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(shutil, "which", lambda name: None)
    gitignore = project.parent.parent / ".gitignore"
    gitignore.write_text(gitignore.read_text().replace("data/tmp/", ""))
    assert jsa(project, "doctor") == int(ExitCode.CONFIG_ERROR)


# --- pending --------------------------------------------------------------------


def queue_pending(root: Path) -> Harness:
    from job_search_agent.models import BackendErrorKind
    from job_search_agent.pipeline import run_once

    h = Harness.create(root)
    baseline_then(h)
    h.set_backend(FakeBackend([BackendErrorKind.TIMEOUT]))
    run_once(h.deps(h.live_source(Reply(body=ADDED))))
    return h


def test_pending_list_and_drop(
    project: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    h = queue_pending(project.parent.parent)
    assert jsa(project, "pending", "list") == 0
    out = capsys.readouterr().out
    assert f"{CONSTRUCTED_ID} last_status=ERROR attempts=1" in out
    assert jsa(project, "pending", "drop", str(CONSTRUCTED_ID), "--reason", "  ") == 5
    assert jsa(project, "pending", "drop", "1", "--reason", "x") == 5
    assert (
        jsa(project, "pending", "drop", str(CONSTRUCTED_ID), "--reason", "withdrawn")
        == 0
    )
    state = parse_state(h.data("live/state.json").read_bytes())
    assert state.pending == []
    assert state.abandoned[0].reason == "withdrawn"
    capsys.readouterr()
    assert jsa(project, "pending", "list", "--data", "seeded") == 0
    assert "absent" in capsys.readouterr().out


def test_pending_drop_fails_fast_while_a_run_holds_the_lock(
    project: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    h = queue_pending(project.parent.parent)
    monkeypatch.setattr(
        cli, "_output_root", lambda cfg: create_output_root(cfg.data_dir)
    )
    before = h.data("live/state.json").read_bytes()
    argv = ("pending", "drop", str(CONSTRUCTED_ID), "--reason", "withdrawn")
    with OutputRoot(h.config.data_dir).lock("live/.lock"):
        assert jsa(project, *argv) == int(ExitCode.LOCKED) == 7
    assert "lock" in capsys.readouterr().err
    assert h.data("live/state.json").read_bytes() == before
    assert jsa(project, *argv) == 0


def test_pending_drop_reads_state_through_the_output_root(
    project: Path, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    h = queue_pending(project.parent.parent)
    reads: list[str] = []

    class Spy(LocalOutputRoot):
        def read_bytes(self, rel: str) -> bytes:
            reads.append(rel)
            return super().read_bytes(rel)

    monkeypatch.setattr(cli, "_output_root", lambda cfg: Spy(cfg.data_dir))
    argv = ("pending", "drop", str(CONSTRUCTED_ID), "--reason", "withdrawn")
    assert jsa(project, *argv) == 0
    assert reads == ["live/state.json"]
    state = h.data("live/state.json")
    outside = tmp_path / "outside.json"
    outside.write_bytes(state.read_bytes())
    state.unlink()
    state.symlink_to(outside)
    monkeypatch.setattr(
        cli, "_output_root", lambda cfg: create_output_root(cfg.data_dir)
    )
    assert jsa(project, *argv) == int(ExitCode.CONFIG_ERROR)


def test_resume_gate_reads_through_the_read_policy(tmp_path: Path) -> None:
    config = make_project(tmp_path)
    under_src = "src/job_search_agent/kiran.resume.example.json"
    (tmp_path / under_src).parent.mkdir(parents=True)
    shutil.copyfile(
        REPO_ROOT / "persona/kiran-joshi.resume.example.json", tmp_path / under_src
    )
    good = load_config(config)
    assert cli._load_resume(good).source_path == good.resume.path
    toml = config.read_text(encoding="utf-8")
    config.write_text(
        toml.replace('"persona/kiran-joshi.resume.example.json"', f'"{under_src}"'),
        encoding="utf-8",
    )
    bad = load_config(config)
    with pytest.raises(ConfigError):
        cli._load_resume(bad)


# --- rule -----------------------------------------------------------------------


def test_rule_prints_one_record_without_judgment(
    project: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    raw = str(project.parent.parent / HANDCHECK_RAW_REL)
    assert jsa(project, "rule", "--raw", raw, "--id", "8249901") == 0
    record = json.loads(capsys.readouterr().out)
    assert record["posting_id"] == "8249901"
    assert "rule_verdict" in record and "model_judgment" not in record
    assert list(record)[:4] == ["posting_id", "title", "location", "updated_at"]
    assert jsa(project, "rule", "--raw", raw, "--id", "1") == int(ExitCode.CONFIG_ERROR)


# --- verify-evidence / docs / audit-privacy -------------------------------------


def test_verify_evidence_detects_tampering(
    project: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    root = project.parent.parent
    h = Harness.create(root)
    baseline_then(h)
    from job_search_agent.pipeline import run_once

    run_once(h.deps(h.replay_source(), seeded=True))
    assert jsa(project, "verify-evidence") == 0
    out = capsys.readouterr().out
    assert out.count("[OK]") == 3  # hand-check meta, live meta, seeded pointer
    assert str(root) not in out
    raw = root / HANDCHECK_RAW_REL
    raw.write_bytes(raw.read_bytes() + b"\n")
    assert jsa(project, "verify-evidence") == int(ExitCode.PARTIAL_FAILURE)
    assert capsys.readouterr().out.count("[MISMATCH]") == 2


def test_docs_render_separates_live_and_seeded(
    project: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    from job_search_agent.pipeline import run_once

    h = Harness.create(project.parent.parent)
    live = run_once(h.deps(h.live_source(Reply(body=handcheck_body()))))
    seeded = run_once(h.deps(h.replay_source(), seeded=True))
    assert jsa(project, "docs", "render") == 0
    out = capsys.readouterr().out
    live_part, seeded_part = out.split("## Seeded runs")
    assert live.run_id in live_part and seeded.run_id not in live_part
    assert seeded.run_id in seeded_part


def test_audit_privacy_delegates_to_privacy_module(
    project: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: dict[str, Any] = {}

    def scan_tree(root: Path, values: object) -> list[Finding]:
        calls["root"] = root
        return [Finding(FindingKind.RESUME_VALUE, "live/x.json", 1, 2, "$.p.email")]

    monkeypatch.setattr(cli, "sensitive_values", lambda resume: ())
    monkeypatch.setattr(cli, "scan_tree", scan_tree)
    assert jsa(project, "audit-privacy", str(project.parent.parent / "data")) == 1
    out = capsys.readouterr().out
    assert "[FINDING] live/x.json:1:2 RESUME_VALUE $.p.email" in out
    assert "1 finding(s)" in out and "audit-privacy data:" in out
    assert calls["root"] == project.parent.parent / "data"


def test_main_reports_agent_error_without_path(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    secret_dir = tmp_path / "secret-dir"
    assert cli.main(["--config", str(secret_dir / "agent.toml"), "doctor"]) == 5
    assert str(secret_dir) not in capsys.readouterr().err


def test_namespace_handlers_all_set() -> None:
    parser = cli.build_parser()
    for argv in (
        ["run"],
        ["doctor"],
        ["pending", "list"],
        ["pending", "drop", "1", "--reason", "r"],
        ["rule", "--raw", "x", "--id", "1"],
        ["verify-evidence"],
        ["audit-privacy"],
        ["docs", "render"],
    ):
        ns: argparse.Namespace = parser.parse_args(argv)
        assert callable(ns.handler)
