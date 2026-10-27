"""Tests for the shared .NET target discovery helper."""

from __future__ import annotations

import importlib.util
import subprocess
from pathlib import Path
from typing import TYPE_CHECKING
from unittest.mock import MagicMock, patch

import pytest

if TYPE_CHECKING:
    import types

MODULE_PATH = Path(__file__).resolve().parents[2] / "src" / "ydk" / "verifications" / "_dotnet_target.py"


def _load_module() -> types.ModuleType:
    spec = importlib.util.spec_from_file_location("dotnet_target", MODULE_PATH)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


mod = _load_module()


def _touch(root: Path, rel: str) -> Path:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("", encoding="utf-8")
    return path


def _version(stdout: str, returncode: int = 0) -> MagicMock:
    return MagicMock(return_value=subprocess.CompletedProcess([], returncode, stdout=stdout, stderr=""))


def test_find_targets_none(tmp_path: Path) -> None:
    with patch("subprocess.run") as run:
        assert mod.find_targets(str(tmp_path), "dotnet") == []
    run.assert_not_called()


def test_sln_beats_slnx_without_sdk_check(tmp_path: Path) -> None:
    _touch(tmp_path, "a.slnx")
    sln = _touch(tmp_path, "deep/x/b.sln")
    with patch("subprocess.run") as run:
        assert mod.find_targets(str(tmp_path), "dotnet") == [str(sln)]
    run.assert_not_called()


def test_shallowest_sln_wins_over_sorted_first(tmp_path: Path) -> None:
    zzz = _touch(tmp_path, "zzz.sln")
    _touch(tmp_path, "a/aaa.sln")
    assert mod.find_targets(str(tmp_path), "dotnet") == [str(zzz)]


@pytest.mark.parametrize("ver", ["9.0.200", "10.0.100"])
def test_slnx_used_on_new_sdk(tmp_path: Path, ver: str) -> None:
    slnx = _touch(tmp_path, "a.slnx")
    _touch(tmp_path, "p/p.csproj")
    with patch("subprocess.run", _version(ver + "\n")) as run:
        assert mod.find_targets(str(tmp_path), "dotnet") == [str(slnx)]
    assert run.call_args.kwargs["cwd"] == str(tmp_path)


@pytest.mark.parametrize("ver", ["8.0.100", "9.0.100"])
def test_slnx_skipped_on_old_sdk(tmp_path: Path, ver: str) -> None:
    _touch(tmp_path, "a.slnx")
    proj = _touch(tmp_path, "p/p.csproj")
    with patch("subprocess.run", _version(ver)):
        assert mod.find_targets(str(tmp_path), "dotnet") == [str(proj)]


@pytest.mark.parametrize("failure", [_version("9.0.200", 1), MagicMock(side_effect=OSError)])
def test_slnx_skipped_when_version_fails(tmp_path: Path, failure: MagicMock) -> None:
    _touch(tmp_path, "a.slnx")
    proj = _touch(tmp_path, "p/p.csproj")
    with patch("subprocess.run", failure):
        assert mod.find_targets(str(tmp_path), "dotnet") == [str(proj)]


def test_all_csproj_returned(tmp_path: Path) -> None:
    a = _touch(tmp_path, "a/A.csproj")
    b = _touch(tmp_path, "b/c/B.csproj")
    assert mod.find_targets(str(tmp_path), "dotnet") == sorted([str(a), str(b)])


def test_test_only_filters_stems(tmp_path: Path) -> None:
    _touch(tmp_path, "App/App.csproj")
    t1 = _touch(tmp_path, "App.Tests/App.Tests.csproj")
    t2 = _touch(tmp_path, "T/Foo.Test.csproj")
    assert mod.find_targets(str(tmp_path), "dotnet", test_only=True) == sorted([str(t1), str(t2)])


def test_excluded_dirs_ignored(tmp_path: Path) -> None:
    for d in ("third_party", ".vs", "bin", "obj"):
        _touch(tmp_path, f"{d}/x.sln")
        _touch(tmp_path, f"{d}/x.csproj")
    real = _touch(tmp_path, "src/Real.csproj")
    assert mod.find_targets(str(tmp_path), "dotnet") == [str(real)]


def test_excluded_name_in_root_ancestors_not_applied(tmp_path: Path) -> None:
    root = tmp_path / "bin" / "repo"
    sln = _touch(root, "a.sln")
    assert mod.find_targets(str(root), "dotnet") == [str(sln)]


@pytest.mark.parametrize("name", ["missing.sln", "somedir", "x.cs"])
def test_target_problem_bad(tmp_path: Path, name: str) -> None:
    if name == "somedir":
        (tmp_path / name).mkdir()
    elif name == "x.cs":
        _touch(tmp_path, name)
    problem = mod.target_problem(str(tmp_path / name))
    assert problem is not None
    assert problem.startswith("verification.dotnet.target")


@pytest.mark.parametrize("name", ["a.sln", "a.slnx", "a.csproj"])
def test_target_problem_ok(tmp_path: Path, name: str) -> None:
    assert mod.target_problem(str(_touch(tmp_path, name))) is None


def test_configured_target_none() -> None:
    assert mod.configured_target({"project_root": "."}) is None
    assert mod.configured_target({"project_root": ".", "config": {"dotnet": {}}}) is None


def test_configured_target_relative(tmp_path: Path) -> None:
    ctx = {"project_root": str(tmp_path), "config": {"dotnet": {"target": "a/b.sln"}}}
    assert mod.configured_target(ctx) == str((tmp_path / "a" / "b.sln").resolve())


def test_configured_target_absolute(tmp_path: Path) -> None:
    target = str(tmp_path / "abs.sln")
    ctx = {"project_root": "elsewhere", "config": {"dotnet": {"target": target}}}
    assert mod.configured_target(ctx) == target


def test_sdk_supports_slnx_prerelease() -> None:
    with patch("subprocess.run", _version("9.0.200-preview.1\n")):
        assert mod.sdk_supports_slnx("dotnet", ".") is True


def test_sdk_supports_slnx_garbage() -> None:
    with patch("subprocess.run", _version("not a version")):
        assert mod.sdk_supports_slnx("dotnet", ".") is False


def test_sdk_supports_slnx_timeout() -> None:
    with patch("subprocess.run", MagicMock(side_effect=subprocess.TimeoutExpired("dotnet", 15))):
        assert mod.sdk_supports_slnx("dotnet", ".") is False


@pytest.mark.parametrize(
    "files",
    [
        ["src/Foo.cs"],
        ["a/App.fsproj"],
        ["x.SLNX"],
        ["Directory.Build.props"],
        ["build/Common.targets"],
        ["src/.editorconfig"],
        ["global.json"],
        ["sub/NuGet.Config"],
        ["nuget.config"],
        ["README.md", "src/Main.CS"],
    ],
)
def test_affects_dotnet_build_true(files: list[str]) -> None:
    assert mod.affects_dotnet_build(files) is True


@pytest.mark.parametrize("files", [[], ["README.md"], ["docs/guide.md", "package.json", "notglobal.json"]])
def test_affects_dotnet_build_false(files: list[str]) -> None:
    assert mod.affects_dotnet_build(files) is False
