"""Sync bundled Claude skills/agents into the user's Claude config dir."""

from __future__ import annotations

import os
import shutil
from pathlib import Path

STAMP_FILE = ".ydk-version"

_IGNORE = shutil.ignore_patterns("__pycache__", "*.pyc")


def bundled_skills_dir() -> Path:
    """Skills shipped in the wheel (``ydk/_skills``), else the repo ``skills/`` dir for source checkouts."""
    packaged = Path(__file__).resolve().parent.parent / "_skills"
    if packaged.is_dir():
        return packaged
    return Path(__file__).resolve().parents[3] / "skills"


def claude_config_dir() -> Path:
    """``$CLAUDE_CONFIG_DIR`` if set, else ``~/.claude``."""
    env = os.environ.get("CLAUDE_CONFIG_DIR")
    return Path(env) if env else Path.home() / ".claude"


def _skill_dirs(source: Path) -> list[Path]:
    if not source.is_dir():
        return []
    return sorted(p for p in source.iterdir() if (p / "SKILL.md").is_file())


def sync_skills(source: Path, target: Path, version: str, *, dry_run: bool = False) -> list[str]:
    """Copy each skill in *source* to ``target/skills/<name>`` and its ``agents/*.md`` to ``target/agents``.

    Skips ``__pycache__``/``*.pyc`` and stamps each skill with *version*. Returns the actions taken
    (or that would be taken when *dry_run*).
    """
    actions: list[str] = []
    for skill in _skill_dirs(source):
        dest = target / "skills" / skill.name
        actions.append(f"skill {skill.name} -> {dest}")
        if not dry_run:
            if (dest / STAMP_FILE).is_file() and not (dest.is_symlink() or dest.is_junction()):
                shutil.rmtree(dest)  # ydk-owned from a prior sync: replace so removed files don't linger
            shutil.copytree(skill, dest, ignore=_IGNORE, dirs_exist_ok=True)
            (dest / STAMP_FILE).write_text(version + "\n", encoding="utf-8")
        agents = skill / "agents"
        if not agents.is_dir():
            continue
        for agent in sorted(agents.glob("*.md")):
            agent_dest = target / "agents" / agent.name
            actions.append(f"agent {agent.name} -> {agent_dest}")
            if not dry_run:
                agent_dest.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(agent, agent_dest)
    return actions


def skill_status(source: Path, target: Path) -> list[tuple[str, str | None]]:
    """``(name, stamp)`` for each bundled skill; stamp is None when not installed or unstamped."""
    result: list[tuple[str, str | None]] = []
    for skill in _skill_dirs(source):
        stamp = target / "skills" / skill.name / STAMP_FILE
        result.append((skill.name, stamp.read_text(encoding="utf-8").strip() if stamp.is_file() else None))
    return result
