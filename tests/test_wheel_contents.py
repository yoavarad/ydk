"""Built wheel bundles every repo skill and agent file (via `uv build`)."""

from __future__ import annotations

import shutil
import subprocess
import zipfile
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent


@pytest.mark.skipif(shutil.which("uv") is None, reason="uv not installed")
def test_wheel_contains_all_skills_and_agents(tmp_path: Path) -> None:
    build = subprocess.run(
        ["uv", "build", "--wheel", "--out-dir", str(tmp_path)],
        cwd=REPO_ROOT,
        check=False,
        capture_output=True,
        text=True,
    )
    assert build.returncode == 0, build.stderr
    wheel = next(tmp_path.glob("*.whl"))
    names = set(zipfile.ZipFile(wheel).namelist())

    skills_root = REPO_ROOT / "skills"
    expected = {
        "ydk/_skills/" + p.relative_to(skills_root).as_posix()
        for p in skills_root.rglob("*")
        if p.is_file() and "__pycache__" not in p.parts and p.suffix != ".pyc"
    }
    assert expected, "repo skills/ dir is empty"
    assert expected <= names, sorted(expected - names)
    assert "ydk/_skills/orchestrate-ready-tasks/agents/ydk-orchestrator.md" in names
    assert not [n for n in names if "__pycache__" in n and n.startswith("ydk/_skills/")]
