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
