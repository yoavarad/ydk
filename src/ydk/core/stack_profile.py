"""Per-language behaviour for ``task done``, T-FINAL scaffolding and test derivation.

The language is derived from the project's stack (see ``stacks.STACKS``) so
new stacks plug in without code changes: an explicit ``language`` key wins,
then the stack name's first segment (``go``, ``go-service``), then the
presence of the ``go-test`` plugin without ``tests-pytest``. Python is the
default and keeps the legacy behaviour.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from ydk.core.stacks import STACKS

if TYPE_CHECKING:
    from ydk.models.config import YdkConfig


@dataclass(frozen=True)
class LanguageProfile:
    """Language-specific knobs used by task done and scaffold-batch."""

    name: str
    test_layout: str
    test_suffix: str
    skip_label: str
    tfinal_title: str
    tfinal_criteria: tuple[str, ...]
    tfinal_test_strategy: str
    tfinal_summary: str


PROFILES: dict[str, LanguageProfile] = {
    "python": LanguageProfile(
        name="python",
        test_layout="python-tests-dir",
        test_suffix=".py",
        skip_label="xfail for this task's TODOs",
        tfinal_title="Final verification: all tests pass, zero xfail",
        tfinal_criteria=(
            "Zero @pytest.mark.xfail in test suite",
            "Zero NotImplementedError in services",
            "All E2E tests pass",
            "Full ruff + ty clean",
        ),
        tfinal_test_strategy="Run full test suite with --strict-markers, verify zero xfail remaining",
        tfinal_summary="verifies zero xfail",
    ),
    "go": LanguageProfile(
        name="go",
        test_layout="same-dir-suffix",
        test_suffix="_test.go",
        skip_label="skipped without a reason",
        tfinal_title="Final verification: all tests pass, zero un-reasoned skips",
        tfinal_criteria=(
            "Zero t.Skip() without a reason in test suite",
            'Zero panic("not implemented") in code',
            "go test ./... passes",
            "gofmt + go vet clean",
        ),
        tfinal_test_strategy="Run go test ./... and go vet ./..., verify gofmt -l is empty and no un-reasoned t.Skip",
        tfinal_summary="verifies zero un-reasoned t.Skip",
    ),
    "dotnet": LanguageProfile(
        name="dotnet",
        test_layout="dotnet-tests-project",
        test_suffix="Tests.cs",
        skip_label="xUnit [Fact(Skip=...)] without a reason",
        tfinal_title="Final verification: all tests pass, zero un-reasoned skips",
        tfinal_criteria=(
            "Zero xUnit Skip without a reason in test suite",
            "Zero throw new NotImplementedException() in code",
            "dotnet test passes",
            "dotnet format --verify-no-changes clean",
        ),
        tfinal_test_strategy=(
            "Run dotnet test and dotnet format --verify-no-changes, verify no un-reasoned xUnit Skip remaining"
        ),
        tfinal_summary="verifies zero un-reasoned xUnit Skip",
    ),
}


def language_for(stack: str, enabled: list[str] | None = None) -> str:
    """Return the profile language for *stack* (falling back to *enabled* plugins)."""
    stack_def = STACKS.get(stack, {})
    explicit = stack_def.get("language")
    if explicit in PROFILES:
        return explicit
    head = stack.split("-", 1)[0]
    if head in PROFILES:
        return head
    plugins = stack_def.get("verifications") or enabled or []
    if "go-test" in plugins and "tests-pytest" not in plugins:
        return "go"
    return "python"


def profile_for(config: YdkConfig) -> LanguageProfile:
    """Return the language profile for a loaded project config."""
    return PROFILES[language_for(config.project.stack, config.verification.enabled)]
