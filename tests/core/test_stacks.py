"""Tests for technology stack definitions."""

from __future__ import annotations

from pathlib import Path

import pytest

from ydk.core.stacks import STACKS, get_stack


def test_python_fastapi_stack_exists() -> None:
    assert "python-fastapi" in STACKS


def test_python_cli_stack_exists() -> None:
    assert "python-cli" in STACKS


def test_nextjs_fsd_stack_exists() -> None:
    assert "nextjs-fsd" in STACKS


def test_terraform_stack_exists() -> None:
    assert "terraform" in STACKS


def test_dotnet_stack_exists() -> None:
    assert "dotnet" in STACKS


def test_dotnet_stack_verifications() -> None:
    stack = get_stack("dotnet")
    assert stack["verifications"] == [
        "dotnet-build",
        "dotnet-format",
        "dotnet-test",
        "dotnet-quality",
        "dotnet-tdd-guard",
    ]


def test_get_stack_returns_verifications() -> None:
    stack = get_stack("python-fastapi")
    assert "lint-ruff" in stack["verifications"]
    assert "fastapi-route-delegation" in stack["verifications"]


def test_get_stack_unknown_raises() -> None:
    with pytest.raises(KeyError, match="Unknown stack"):
        get_stack("nonexistent-stack")


def test_all_stacks_have_verifications() -> None:
    for name, stack in STACKS.items():
        assert "verifications" in stack, f"Stack {name!r} missing verifications"
        assert len(stack["verifications"]) > 0, f"Stack {name!r} has empty verifications"


GO_PYTHON_PLUGINS = {"lint-ruff", "types-ty", "tests-pytest", "python-quality", "python-tdd-guard"}


def test_go_stack_plugins_are_go_only() -> None:
    stack = get_stack("go")
    enabled = set(stack["verifications"])
    assert {"go-fmt", "go-vet", "go-test", "go-vendor", "helm-lint", "tdd-guard", "tdd-guard-cmd"} <= enabled
    assert not enabled & GO_PYTHON_PLUGINS
    assert all(
        (Path(__file__).parents[2] / "src" / "ydk" / "verifications" / p / "manifest.yaml").is_file() for p in enabled
    )


def test_go_stack_overrides() -> None:
    o = get_stack("go")["config_overrides"]
    assert o["verification.tdd.source_globs"] == ["**/*.go"]
    assert o["verification.tdd.test_globs"] == ["**/*_test.go"]
    assert "vendor/**" in o["verification.tdd.exempt_globs"]
    assert o["verification.tdd.test_for"] == "same-dir-suffix"
    assert o["guards.code_dirs"] == ["cmd", "internal", "pkg", "charts", "scripts", "test"]
    assert o["testing.test_globs"] == ["**/*_test.go"]
