"""Tests for stack_profile — language detection and per-language task-done behaviour."""

from __future__ import annotations

import re

import pytest

from ydk.core import stacks
from ydk.core.stack_profile import PROFILES, language_for, profile_for
from ydk.models.config import YdkConfig


def _config(stack: str = "", enabled: list[str] | None = None) -> YdkConfig:
    return YdkConfig.model_validate(
        {"project": {"name": "p", "stack": stack}, "verification": {"enabled": enabled or []}}
    )


class TestLanguageFor:
    def test_defaults_to_python(self) -> None:
        assert language_for("") == "python"

    @pytest.mark.parametrize("stack", ["python-cli", "python-fastapi", "nextjs-fsd", "dotnet", "terraform"])
    def test_existing_stacks_are_python_behaviour(self, stack: str) -> None:
        assert language_for(stack) == "python"

    def test_stack_name_head_selects_go(self) -> None:
        assert language_for("go") == "go"
        assert language_for("go-service") == "go"

    def test_explicit_language_key_wins(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setitem(stacks.STACKS, "svc", {"language": "go", "verifications": []})
        assert language_for("svc") == "go"

    def test_go_test_plugin_in_stack_selects_go(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setitem(stacks.STACKS, "backend", {"verifications": ["go-fmt", "go-vet", "go-test"]})
        assert language_for("backend") == "go"

    def test_enabled_plugins_used_when_no_stack(self) -> None:
        assert language_for("", ["go-fmt", "go-test"]) == "go"

    def test_mixed_with_pytest_stays_python(self) -> None:
        assert language_for("", ["go-test", "tests-pytest"]) == "python"


class TestProfileFor:
    def test_python_profile_keeps_legacy_tfinal(self) -> None:
        profile = profile_for(_config())
        assert profile is PROFILES["python"]
        assert "Zero @pytest.mark.xfail in test suite" in profile.tfinal_criteria
        assert "Full ruff + ty clean" in profile.tfinal_criteria

    def test_go_profile_criteria_have_no_python_tools(self) -> None:
        profile = profile_for(_config(enabled=["go-test"]))
        assert profile.name == "go"
        text = " ".join([profile.tfinal_title, *profile.tfinal_criteria, profile.tfinal_test_strategy])
        assert 'panic("not implemented")' in text
        assert "gofmt" in text
        assert "go vet" in text
        for python_tool in ("ruff", "ty", "pytest", "xfail"):
            assert not re.search(rf"\b{python_tool}\b", text)
