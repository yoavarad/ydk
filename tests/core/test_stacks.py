"""Tests for technology stack definitions."""

from __future__ import annotations

import pytest

from odk.core.stacks import STACKS, get_stack


def test_python_fastapi_stack_exists() -> None:
    assert "python-fastapi" in STACKS


def test_python_cli_stack_exists() -> None:
    assert "python-cli" in STACKS


def test_nextjs_fsd_stack_exists() -> None:
    assert "nextjs-fsd" in STACKS


def test_terraform_stack_exists() -> None:
    assert "terraform" in STACKS


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
