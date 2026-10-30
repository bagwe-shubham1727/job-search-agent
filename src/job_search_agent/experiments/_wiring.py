"""Production wiring for ``jsa exp``: real adapters, WS1/WS2 modules imported lazily.

Nothing here runs at import time. WS1 (``providers.greenhouse``, ``rule``,
``text``) and WS2 (``fsio``, ``resume``, ``http``) are imported only when a command
needs them, so this package works (and is testable) before those workstreams merge.
"""

from __future__ import annotations

import importlib
import os
import shutil
from collections.abc import Callable, Mapping, Sequence
from functools import cached_property
from pathlib import Path
from typing import Any, cast

from job_search_agent.clock import SystemClock
from job_search_agent.config import AgentConfig, load_config
from job_search_agent.experiments._calls import FirstReplyJudge
from job_search_agent.experiments._io import (
    ExperimentContext,
    LocalRepoReader,
)
from job_search_agent.experiments.prompt_experiment import HANDCHECK_RAW_REL
from job_search_agent.judge.backend import SubprocessRunner, child_env
from job_search_agent.judge.judge import build_backend
from job_search_agent.judge.payload import Cleaner
from job_search_agent.judge.prompt import PromptContract, load_prompt
from job_search_agent.judge.rawlog import RawReplyLog
from job_search_agent.models import Posting, RuleVerdict, VerifiedResume
from job_search_agent.ports import CommandRunner, HttpFetcher

_GIT_TIMEOUT_S = 60.0


class GitCli:
    """``GitInspector`` backed by the ``git`` executable (read-only commands).

    Args:
        runner: Command runner.
        repo_root: Repository root.
        env: Environment for git (defaults to ``os.environ``).
    """

    def __init__(
        self,
        runner: CommandRunner,
        repo_root: Path,
        env: Mapping[str, str] | None = None,
    ) -> None:
        self._runner = runner
        self._root = repo_root
        self._env = dict(os.environ if env is None else env)

    def _git(self, *args: str) -> tuple[int | None, str]:
        done = self._runner.run(
            ("git", *args),
            cwd=self._root,
            env=self._env,
            stdin="",
            timeout_s=_GIT_TIMEOUT_S,
        )
        return done.returncode, done.stdout

    def head(self) -> str:
        """Returns the full hash of HEAD."""
        _, out = self._git("rev-parse", "HEAD")
        return out.strip()

    def is_dirty(self) -> bool:
        """Returns True if tracked files differ from HEAD."""
        _, out = self._git("status", "--porcelain", "--untracked-files=no")
        return bool(out.strip())

    def is_tracked_and_clean(self, path: Path) -> bool:
        """Returns True if ``path`` is tracked and equal to HEAD (staged or not)."""
        rel = path.as_posix()
        code, _ = self._git("ls-files", "--error-unmatch", "--", rel)
        if code != 0:
            return False
        code, _ = self._git("diff", "--quiet", "HEAD", "--", rel)
        return code == 0


def _module(name: str) -> Any:  # noqa: ANN401 - lazily imported module
    return importlib.import_module(name)


class Wiring:
    """Builds the real dependencies for one ``jsa exp`` invocation.

    Args:
        config_path: ``--config`` value.
    """

    def __init__(self, config_path: Path) -> None:
        self._config_path = config_path

    @cached_property
    def config(self) -> AgentConfig:
        """The validated configuration."""
        return load_config(self._config_path)

    @cached_property
    def runner(self) -> CommandRunner:
        """The subprocess runner."""
        return SubprocessRunner()

    @cached_property
    def out(self) -> Any:  # noqa: ANN401 - WS2 OutputRoot
        """WS2 ``fsio.OutputRoot`` on the data directory."""
        return _module("job_search_agent.fsio").OutputRoot(self.config.data_dir)

    @cached_property
    def context(self) -> ExperimentContext:
        """Shared experiment dependencies."""
        root = self.config.project_root
        return ExperimentContext(
            writer=self.out,
            reader=LocalRepoReader(root),
            git=GitCli(self.runner, root),
            clock=SystemClock(),
            data_dir=self.config.data_dir.relative_to(root).as_posix(),
        )

    @cached_property
    def resume(self) -> VerifiedResume:
        """The verified résumé (WS2 gate)."""
        gate = _module("job_search_agent.resume")
        return cast(
            VerifiedResume,
            gate.load_verified_resume(
                self.config.resume_path, self.config.resume.pinned_sha256
            ),
        )

    @cached_property
    def clean(self) -> Cleaner:
        """WS1 ``text.clean_html``."""
        return cast(Cleaner, _module("job_search_agent.text").clean_html)

    def evaluate(self) -> Callable[[Posting], RuleVerdict]:
        """WS1's rule with the verified résumé bound."""
        rule = _module("job_search_agent.rule.verdict")
        resume = self.resume
        return lambda posting: cast(RuleVerdict, rule.evaluate(posting, resume))

    @cached_property
    def handcheck_postings(self) -> Sequence[Posting]:
        """Postings of the committed hand-check raw file (WS1 parser)."""
        provider = _module("job_search_agent.providers.greenhouse").GreenhouseProvider()
        body = self.context.reader.read_bytes(HANDCHECK_RAW_REL)
        return tuple(provider.parse(body).postings)

    def postings_by_id(self) -> dict[str, Posting]:
        """Hand-check postings keyed by ID."""
        return {p.posting_id: p for p in self.handcheck_postings}

    def load_prompt(self, version: str) -> PromptContract:
        """Loads ``prompts/judge.<version>.md``."""
        return load_prompt(self.config.project_root, version)

    def judge_call(self) -> FirstReplyJudge:
        """A first-reply judge on the configured backend."""
        backend = build_backend(
            self.config.model,
            runner=self.runner,
            make_empty_dir=self.out.make_empty_dir,
            clock=SystemClock(),
        )
        return FirstReplyJudge(
            backend=backend,
            resume=self.resume,
            rawlog=RawReplyLog(self.out, repo_rel=self.config.repo_rel),
            model_requested=self.config.model.model_id,
            clean=self.clean,
        )

    def fetcher(self) -> HttpFetcher:
        """WS2's allow-listed fetcher."""
        http = self.config.http
        return cast(
            HttpFetcher,
            _module("job_search_agent.http").build_fetcher(
                http.allowed_hosts,
                timeout_s=http.timeout_s,
                max_bytes=http.max_bytes,
                max_redirects=http.max_redirects,
                user_agent=http.user_agent,
            ),
        )

    def child_env(self) -> dict[str, str]:
        """The R1 child environment."""
        return child_env(os.environ)

    @staticmethod
    def which(name: str) -> str | None:
        """``shutil.which``."""
        return shutil.which(name)
