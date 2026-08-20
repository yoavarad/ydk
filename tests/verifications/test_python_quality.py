"""Tests for the python-quality verification plugin's tool resolution."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import types

CHECK_SCRIPT = Path(__file__).resolve().parents[2] / "src" / "ydk" / "verifications" / "python-quality" / "check.py"


def _load_check_module() -> types.ModuleType:
    """Import python-quality's check.py as a module for direct testing."""
    spec = importlib.util.spec_from_file_location("python_quality_check", CHECK_SCRIPT)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class TestResolveVenvBinary:
    """_resolve_venv_binary prefers the project's own venv over a PATH lookup."""

    def test_prefers_venv_local_binary_when_present(self, tmp_path: Path) -> None:
        mod = _load_check_module()
        venv_dir = "Scripts" if sys.platform == "win32" else "bin"
        suffix = ".exe" if sys.platform == "win32" else ""
        tool_path = tmp_path / ".venv" / venv_dir / f"ruff{suffix}"
        tool_path.parent.mkdir(parents=True)
        tool_path.write_text("")

        assert mod._resolve_venv_binary(str(tmp_path), "ruff") == str(tool_path)

    def test_falls_back_to_bare_name_when_no_venv(self, tmp_path: Path) -> None:
        mod = _load_check_module()

        assert mod._resolve_venv_binary(str(tmp_path), "ruff") == "ruff"


class TestDiscoverTyDirs:
    """_discover_ty_dirs expands around a catalog directory when present."""

    def test_expands_src_excluding_catalog_when_present(self, tmp_path: Path) -> None:
        (tmp_path / "src" / "ydk" / "catalog").mkdir(parents=True)
        (tmp_path / "src" / "ydk" / "core").mkdir(parents=True)
        mod = _load_check_module()

        dirs = mod._discover_ty_dirs(str(tmp_path), ["src"])

        assert "src" not in dirs
        assert "src/ydk" not in dirs
        assert not any("catalog" in d for d in dirs)
        assert "src/ydk/core" in dirs

    def test_unchanged_when_no_catalog_dir(self, tmp_path: Path) -> None:
        mod = _load_check_module()

        dirs = mod._discover_ty_dirs(str(tmp_path), ["src"])

        assert dirs == ["src"]

    def test_unchanged_when_src_not_in_dirs(self, tmp_path: Path) -> None:
        (tmp_path / "src" / "ydk" / "catalog").mkdir(parents=True)
        mod = _load_check_module()

        dirs = mod._discover_ty_dirs(str(tmp_path), ["app"])

        assert dirs == ["app"]


class TestBuildTyCmd:
    def test_uses_discovered_ty_dirs(self, tmp_path: Path) -> None:
        (tmp_path / "src" / "ydk" / "catalog").mkdir(parents=True)
        (tmp_path / "src" / "ydk" / "core").mkdir(parents=True)
        mod = _load_check_module()

        cmd = mod._build_ty_cmd("ty", str(tmp_path), ["src"])

        assert cmd[:2] == ["ty", "check"]
        assert not any("catalog" in part for part in cmd)
        assert cmd[-2:] == ["--python-version", "3.12"]
