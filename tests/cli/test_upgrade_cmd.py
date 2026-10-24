"""Tests for `ydk upgrade` — the uv subprocess boundary is mocked."""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import TYPE_CHECKING

from typer.testing import CliRunner

from ydk.cli import app, upgrade_cmd

if TYPE_CHECKING:
    import pytest

runner = CliRunner()


def _fake(
    calls: list[list[str]],
    tool_list: str = "ydk v9.9.9\n- ydk\n",
    fail_on: str | None = None,
    bindir: Path = Path("nonexistent-bin"),
):
    def run(cmd: list[str]) -> subprocess.CompletedProcess[str]:
        calls.append(cmd)
        if fail_on and fail_on in cmd:
            return subprocess.CompletedProcess(cmd, 1, "", "boom")
        if cmd[:4] == ["uv", "tool", "dir", "--bin"]:
            return subprocess.CompletedProcess(cmd, 0, str(bindir), "")
        out = tool_list if cmd[:3] == ["uv", "tool", "list"] else "Synced 3 item(s)\n"
        return subprocess.CompletedProcess(cmd, 0, out, "")

    return run


def test_upgrade_runs_uv_then_syncs_and_reports_versions(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[list[str]] = []
    monkeypatch.setattr(upgrade_cmd, "_is_editable", lambda: False)
    monkeypatch.setattr(upgrade_cmd, "_run", _fake(calls))
    result = runner.invoke(app, ["upgrade"])
    assert result.exit_code == 0, result.output
    assert calls[0] == ["uv", "tool", "upgrade", "ydk"]
    assert calls[-1][-2:] == ["skills", "sync"]
    assert "->" in result.output
    assert "9.9.9" in result.output


def test_upgrade_pinned_installs_tag(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[list[str]] = []
    monkeypatch.setattr(upgrade_cmd, "_is_editable", lambda: False)
    monkeypatch.setattr(upgrade_cmd, "_run", _fake(calls))
    result = runner.invoke(app, ["upgrade", "--version", "1.2.3"])
    assert result.exit_code == 0, result.output
    assert calls[0] == ["uv", "tool", "install", "--force", "git+https://github.com/yoavarad/ydk@v1.2.3"]


def test_upgrade_refuses_editable_install(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[list[str]] = []
    monkeypatch.setattr(upgrade_cmd, "_is_editable", lambda: True)
    monkeypatch.setattr(upgrade_cmd, "_run", _fake(calls))
    result = runner.invoke(app, ["upgrade"])
    assert result.exit_code == 1
    assert "Editable" in result.output
    assert calls == []


def test_upgrade_uv_failure_skips_sync(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[list[str]] = []
    monkeypatch.setattr(upgrade_cmd, "_is_editable", lambda: False)
    monkeypatch.setattr(upgrade_cmd, "_run", _fake(calls, fail_on="upgrade"))
    result = runner.invoke(app, ["upgrade"])
    assert result.exit_code == 1
    assert len(calls) == 1


def test_is_editable_reads_direct_url(monkeypatch: pytest.MonkeyPatch) -> None:
    class Dist:
        def read_text(self, name: str) -> str:
            return '{"url": "file:///x", "dir_info": {"editable": true}}'

    monkeypatch.setattr(upgrade_cmd.importlib.metadata, "distribution", lambda _n: Dist())
    assert upgrade_cmd._is_editable() is True


def test_sync_uses_uv_tool_bin_dir_binary(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    exe = tmp_path / "ydk.exe"
    exe.write_text("")
    calls: list[list[str]] = []
    monkeypatch.setattr(upgrade_cmd, "_is_editable", lambda: False)
    monkeypatch.setattr(upgrade_cmd, "_run", _fake(calls, bindir=tmp_path))
    result = runner.invoke(app, ["upgrade"])
    assert result.exit_code == 0, result.output
    assert calls[-1] == [str(exe), "skills", "sync"]


def test_locked_exe_failure_prints_guidance_and_skips_sync(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[list[str]] = []
    monkeypatch.setattr(upgrade_cmd, "_is_editable", lambda: False)
    monkeypatch.setattr(upgrade_cmd.sys, "platform", "win32")
    monkeypatch.setattr(upgrade_cmd, "_run", _fake(calls, fail_on="upgrade"))
    result = runner.invoke(app, ["upgrade"])
    assert result.exit_code == 1
    assert "not running" in result.output
    assert not any("sync" in c for c in calls)
