"""Tests for quick dev fast path."""

from __future__ import annotations

import subprocess
from typing import TYPE_CHECKING

from ydk.core.quickdev import QuickDevSetup, _generate_task_id, _slugify

if TYPE_CHECKING:
    from pathlib import Path
from ydk.models.quickdev import QuickDevContext


class TestGenerateTaskId:
    def test_produces_qd_prefix(self) -> None:
        tid = _generate_task_id("fix the bug")
        assert tid.startswith("QD-")

    def test_deterministic(self) -> None:
        a = _generate_task_id("same description")
        b = _generate_task_id("same description")
        assert a == b

    def test_different_for_different_input(self) -> None:
        a = _generate_task_id("fix A")
        b = _generate_task_id("fix B")
        assert a != b


class TestSlugify:
    def test_basic_slugify(self) -> None:
        assert _slugify("Hello World") == "hello-world"

    def test_special_chars(self) -> None:
        result = _slugify("fix: the bug!")
        assert result == "fix-the-bug"

    def test_max_length(self) -> None:
        result = _slugify("a" * 100, max_len=10)
        assert len(result) <= 10


class TestQuickDevSetup:
    def test_creates_task_file(self, tmp_path: Path) -> None:
        # Initialize a git repo so branch creation works
        subprocess.run(["git", "init"], cwd=str(tmp_path), capture_output=True)
        subprocess.run(
            ["git", "commit", "--allow-empty", "-m", "init"],
            cwd=str(tmp_path),
            capture_output=True,
        )

        setup = QuickDevSetup()
        result = setup.setup("add user avatar", tmp_path)

        assert isinstance(result, QuickDevContext)
        assert result.task_id.startswith("QD-")
        assert "add-user-avatar" in result.branch
        assert result.description == "add user avatar"

        # Task file should exist
        task_file = tmp_path / ".ydk" / "tasks" / f"{result.task_id}.md"
        assert task_file.exists()
        content = task_file.read_text()
        assert "add user avatar" in content
        assert "status: in-progress" in content

    def test_finds_relevant_components(self, tmp_path: Path) -> None:
        subprocess.run(["git", "init"], cwd=str(tmp_path), capture_output=True)
        subprocess.run(
            ["git", "commit", "--allow-empty", "-m", "init"],
            cwd=str(tmp_path),
            capture_output=True,
        )
        # Create components
        components = tmp_path / ".ydk" / "components"
        components.mkdir(parents=True)
        (components / "avatar.yaml").write_text("id: avatar")
        (components / "order.yaml").write_text("id: order")

        setup = QuickDevSetup()
        result = setup.setup("fix avatar upload", tmp_path)
        assert "avatar" in result.components

    def test_context_output(self, tmp_path: Path) -> None:
        subprocess.run(["git", "init"], cwd=str(tmp_path), capture_output=True)
        subprocess.run(
            ["git", "commit", "--allow-empty", "-m", "init"],
            cwd=str(tmp_path),
            capture_output=True,
        )

        setup = QuickDevSetup()
        result = setup.setup("update readme", tmp_path)
        assert result.testing_guidance != ""
        assert result.branch.startswith("quickdev/")
