"""Tests for bundled skill sync into a Claude config dir (always a tmp dir)."""

from __future__ import annotations

from typing import TYPE_CHECKING

from ydk.core.skills_sync import (
    STAMP_FILE,
    bundled_skills_dir,
    claude_config_dir,
    skill_status,
    sync_skills,
)

if TYPE_CHECKING:
    from pathlib import Path

    import pytest


def _make_source(root: Path) -> Path:
    src = root / "skills"
    (src / "alpha" / "scripts" / "__pycache__").mkdir(parents=True)
    (src / "alpha" / "SKILL.md").write_text("# alpha\n")
    (src / "alpha" / "scripts" / "run.py").write_text("print(1)\n")
    (src / "alpha" / "scripts" / "__pycache__" / "run.cpython-313.pyc").write_bytes(b"\x00")
    (src / "alpha" / "scripts" / "stray.pyc").write_bytes(b"\x00")
    (src / "beta" / "agents").mkdir(parents=True)
    (src / "beta" / "SKILL.md").write_text("# beta\n")
    (src / "beta" / "agents" / "helper.md").write_text("agent\n")
    (src / "not-a-skill").mkdir()
    return src


class TestClaudeConfigDir:
    def test_uses_env_var(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(tmp_path / "cfg"))
        assert claude_config_dir() == tmp_path / "cfg"

    def test_defaults_to_home(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("CLAUDE_CONFIG_DIR", raising=False)
        monkeypatch.setenv("HOME", str(tmp_path))
        monkeypatch.setenv("USERPROFILE", str(tmp_path))
        assert claude_config_dir() == tmp_path / ".claude"


class TestBundledSkillsDir:
    def test_contains_repo_skills_and_agents(self) -> None:
        bundled = bundled_skills_dir()
        assert (bundled / "ydk" / "SKILL.md").is_file()
        assert (bundled / "orchestrate-ready-tasks" / "agents" / "ydk-orchestrator.md").is_file()


class TestSyncSkills:
    def test_copies_skills_agents_and_stamps(self, tmp_path: Path) -> None:
        src = _make_source(tmp_path)
        target = tmp_path / "claude"
        sync_skills(src, target, "9.9.9")

        alpha = target / "skills" / "alpha"
        assert (alpha / "SKILL.md").read_text() == "# alpha\n"
        assert (alpha / "scripts" / "run.py").is_file()
        assert (alpha / STAMP_FILE).read_text().strip() == "9.9.9"
        assert (target / "skills" / "beta" / STAMP_FILE).read_text().strip() == "9.9.9"
        assert (target / "agents" / "helper.md").read_text() == "agent\n"
        assert not (target / "skills" / "not-a-skill").exists()

    def test_never_copies_pycache_or_pyc(self, tmp_path: Path) -> None:
        src = _make_source(tmp_path)
        target = tmp_path / "claude"
        sync_skills(src, target, "1.0.0")
        copied = [p.name for p in (target / "skills").rglob("*")]
        assert "__pycache__" not in copied
        assert not any(name.endswith(".pyc") for name in copied)

    def test_updates_existing_install(self, tmp_path: Path) -> None:
        src = _make_source(tmp_path)
        target = tmp_path / "claude"
        sync_skills(src, target, "1.0.0")
        (src / "alpha" / "SKILL.md").write_text("# alpha v2\n")
        sync_skills(src, target, "2.0.0")
        alpha = target / "skills" / "alpha"
        assert (alpha / "SKILL.md").read_text() == "# alpha v2\n"
        assert (alpha / STAMP_FILE).read_text().strip() == "2.0.0"

    def test_update_prunes_files_removed_upstream(self, tmp_path: Path) -> None:
        src = _make_source(tmp_path)
        target = tmp_path / "claude"
        sync_skills(src, target, "1.0.0")
        (src / "alpha" / "scripts" / "run.py").unlink()
        sync_skills(src, target, "2.0.0")
        assert not (target / "skills" / "alpha" / "scripts" / "run.py").exists()

    def test_unstamped_existing_dir_is_overlaid_not_deleted(self, tmp_path: Path) -> None:
        src = _make_source(tmp_path)
        target = tmp_path / "claude"
        user_file = target / "skills" / "alpha" / "mine.md"
        user_file.parent.mkdir(parents=True)
        user_file.write_text("keep")
        sync_skills(src, target, "1.0.0")
        assert user_file.read_text() == "keep"

    def test_dry_run_writes_nothing(self, tmp_path: Path) -> None:
        src = _make_source(tmp_path)
        target = tmp_path / "claude"
        actions = sync_skills(src, target, "1.0.0", dry_run=True)
        assert not target.exists()
        joined = "\n".join(actions)
        assert "alpha" in joined
        assert "helper.md" in joined


class TestSkillStatus:
    def test_reports_stamps(self, tmp_path: Path) -> None:
        src = _make_source(tmp_path)
        target = tmp_path / "claude"
        sync_skills(src, target, "1.0.0")
        (target / "skills" / "beta" / STAMP_FILE).unlink()
        status = dict(skill_status(src, target))
        assert status == {"alpha": "1.0.0", "beta": None}

    def test_not_installed_is_none(self, tmp_path: Path) -> None:
        src = _make_source(tmp_path)
        assert dict(skill_status(src, tmp_path / "empty")) == {"alpha": None, "beta": None}
