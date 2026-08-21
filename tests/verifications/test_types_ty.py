"""Tests for the types-ty verification plugin's graceful degradation.

Covers: skip (not fail) when ``ty`` isn't on PATH, e.g. a non-Python
project or a machine where ty isn't installed (GitHub issue #3).
"""

from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import TYPE_CHECKING
from unittest.mock import patch

if TYPE_CHECKING:
    import types

CHECK_SCRIPT = Path(__file__).resolve().parents[2] / "src" / "ydk" / "verifications" / "types-ty" / "check.py"


def _load_check_module() -> types.ModuleType:
    """Import types-ty's check.py as a module for direct testing."""
    spec = importlib.util.spec_from_file_location("types_ty_check", CHECK_SCRIPT)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_skips_when_ty_not_on_path(tmp_path: Path) -> None:
    """When ty isn't installed, the plugin passes (skips) instead of crashing."""
    env = dict(os.environ)
    env["PATH"] = ""
    result = subprocess.run(
        [sys.executable, str(CHECK_SCRIPT)],
        input=json.dumps({"project_root": str(tmp_path)}),
        capture_output=True,
        text=True,
        env=env,
    )
    assert result.returncode == 0, result.stderr
    data = json.loads(result.stdout)
    assert data["passed"] is True
    assert "ty not found" in data["output"]


class TestResolveTy:
    """_resolve_ty prefers the project's own venv over a PATH lookup."""

    def test_prefers_venv_local_binary_when_present(self, tmp_path: Path) -> None:
        mod = _load_check_module()
        venv_dir = "Scripts" if sys.platform == "win32" else "bin"
        suffix = ".exe" if sys.platform == "win32" else ""
        tool_path = tmp_path / ".venv" / venv_dir / f"ty{suffix}"
        tool_path.parent.mkdir(parents=True)
        tool_path.write_text("")

        assert mod._resolve_ty(str(tmp_path)) == str(tool_path)

    def test_falls_back_to_path_when_no_venv(self, tmp_path: Path) -> None:
        mod = _load_check_module()
        with patch("shutil.which", return_value="/usr/bin/ty"):
            assert mod._resolve_ty(str(tmp_path)) == "/usr/bin/ty"


class TestDiscoverSrcDirs:
    """_discover_src_dirs expands around a catalog directory when present."""

    def test_expands_src_excluding_catalog_when_present(self, tmp_path: Path) -> None:
        (tmp_path / "src" / "ydk" / "catalog").mkdir(parents=True)
        (tmp_path / "src" / "ydk" / "core").mkdir(parents=True)
        (tmp_path / "src" / "ydk" / "cli").mkdir(parents=True)
        mod = _load_check_module()

        dirs = mod._discover_src_dirs(str(tmp_path))

        assert "src" not in dirs
        assert "src/ydk" not in dirs
        assert not any("catalog" in d for d in dirs)
        assert "src/ydk/core" in dirs
        assert "src/ydk/cli" in dirs

    def test_returns_plain_src_when_no_catalog_dir(self, tmp_path: Path) -> None:
        (tmp_path / "src").mkdir()
        mod = _load_check_module()

        dirs = mod._discover_src_dirs(str(tmp_path))

        assert dirs == ["src"]

    def test_returns_dot_when_no_src_or_app(self, tmp_path: Path) -> None:
        mod = _load_check_module()

        dirs = mod._discover_src_dirs(str(tmp_path))

        assert dirs == ["."]


class TestBuildCmd:
    def test_scopes_to_changed_files_when_given(self, tmp_path: Path) -> None:
        mod = _load_check_module()

        cmd = mod._build_cmd("ty", str(tmp_path), ["src/ydk/core/config.py"])

        assert cmd == ["ty", "check", "--project", str(tmp_path), "src/ydk/core/config.py"]

    def test_uses_discovered_src_dirs_when_not_scoped(self, tmp_path: Path) -> None:
        (tmp_path / "src").mkdir()
        mod = _load_check_module()

        cmd = mod._build_cmd("ty", str(tmp_path), None)

        assert cmd == ["ty", "check", "--project", str(tmp_path), "src"]
