"""Shared pytest configuration.

Disable Rich color output for the test session. Without this, a dev shell
that sets FORCE_COLOR (as this environment's Bash tool does) makes the
``ydk.output.console`` singleton emit ANSI escape codes even when Typer's
CliRunner captures output to a non-tty stream, breaking plain-text
assertions in CLI tests. Must run before ``ydk.output.console`` is first
imported, so this sets the environment at conftest module level (loaded by
pytest before test modules are collected/imported).
"""

import os

os.environ.pop("FORCE_COLOR", None)
os.environ["NO_COLOR"] = "1"


import pytest


@pytest.fixture(autouse=True)
def _hermetic_default_branch(monkeypatch: pytest.MonkeyPatch):
    """Keep ``default_branch`` off the network: stub the ``gh`` boundary, clear the cache.

    Real ``git`` still runs, so tests set ``origin/HEAD`` via ``git symbolic-ref``.
    """
    from ydk.services import git as git_service

    real = git_service._run_text

    def _no_gh(cmd: list[str], cwd: object, timeout: int) -> str:
        return "" if cmd[0] == "gh" else real(cmd, cwd, timeout)  # type: ignore[arg-type]

    monkeypatch.setattr(git_service, "_run_text", _no_gh)
    git_service._default_branch_cached.cache_clear()
    yield
    git_service._default_branch_cached.cache_clear()
