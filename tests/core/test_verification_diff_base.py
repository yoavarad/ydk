"""spec-alignment and ai-code-review diff against merge-base with the base branch."""

from __future__ import annotations

import importlib.util
import subprocess
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from types import ModuleType

_VERIF = Path(__file__).resolve().parent.parent.parent / "src" / "ydk" / "verifications"
_CHECKS = {
    "spec-alignment": _VERIF / "spec-alignment" / "check.py",
    "ai-code-review": _VERIF / "ai-code-review" / "check.py",
}


def _load(name: str) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name.replace("-", "_") + "_diffbase", _CHECKS[name])
    assert spec is not None
    assert spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _git(root: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", "-c", "user.name=t", "-c", "user.email=t@t", *args],
        cwd=str(root),
        capture_output=True,
        text=True,
        check=True,
    )
    return result.stdout.strip()


def _commit(root: Path, rel: str, content: str, msg: str) -> None:
    (root / rel).write_text(content, encoding="utf-8")
    _git(root, "add", rel)
    _git(root, "commit", "-q", "-m", msg)


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    """Feature branch cut from main; main then advances (touching shared.py) after the cut."""
    _git(tmp_path, "init", "-q", "-b", "main")
    _commit(tmp_path, "shared.py", "v1\n", "base")
    _commit(tmp_path, "feature.py", "old\n", "base2")
    _git(tmp_path, "checkout", "-q", "-b", "feat")
    _commit(tmp_path, "feature.py", "new\n", "feature work")
    _git(tmp_path, "checkout", "-q", "main")
    _commit(tmp_path, "shared.py", "v2-from-main\n", "main advances")
    _git(tmp_path, "checkout", "-q", "feat")
    return tmp_path


@pytest.mark.parametrize("name", list(_CHECKS))
def test_diff_excludes_base_branch_advances(name: str, repo: Path) -> None:
    mod = _load(name)
    out = mod._get_git_diff(repo, ["feature.py", "shared.py"])
    assert "+new" in out
    assert "v2-from-main" not in out


@pytest.mark.parametrize("name", list(_CHECKS))
def test_prefers_origin_base_over_stale_local_main(name: str, tmp_path: Path) -> None:
    """Local main is stale (at A); origin/main is at B; branch forks from B. Merge-bases differ (A vs B)."""
    _git(tmp_path, "init", "-q", "-b", "main")
    _commit(tmp_path, "shared.py", "v1\n", "A")
    _commit(tmp_path, "feature.py", "old\n", "A2")
    stale = _git(tmp_path, "rev-parse", "HEAD")
    _commit(tmp_path, "shared.py", "v2-from-origin\n", "B")
    newer = _git(tmp_path, "rev-parse", "HEAD")
    _git(tmp_path, "update-ref", "refs/remotes/origin/main", newer)
    _git(tmp_path, "checkout", "-q", "-b", "feat")
    _git(tmp_path, "branch", "-f", "main", stale)
    _commit(tmp_path, "feature.py", "new\n", "feature work")
    assert _git(tmp_path, "merge-base", "main", "HEAD") == stale
    assert _git(tmp_path, "merge-base", "origin/main", "HEAD") == newer

    mod = _load(name)
    out = mod._get_git_diff(tmp_path, ["feature.py", "shared.py"])
    assert "+new" in out
    assert "v2-from-origin" not in out


@pytest.mark.parametrize("name", list(_CHECKS))
def test_no_base_branch_falls_back_to_head(name: str, tmp_path: Path) -> None:
    _git(tmp_path, "init", "-q", "-b", "trunk")
    _commit(tmp_path, "a.py", "1\n", "init")
    (tmp_path / "a.py").write_text("2\n", encoding="utf-8")
    mod = _load(name)
    out = mod._get_git_diff(tmp_path, ["a.py"])
    assert "+2" in out
