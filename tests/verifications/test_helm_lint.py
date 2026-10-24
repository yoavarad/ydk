"""Tests for the helm-lint verification plugin.

The helm subprocess is mocked at the system boundary.
"""

from __future__ import annotations

import importlib.util
import io
import json
import sys
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    import types

CHECK_SCRIPT = Path(__file__).resolve().parents[2] / "src" / "ydk" / "verifications" / "helm-lint" / "check.py"


def _load() -> types.ModuleType:
    spec = importlib.util.spec_from_file_location("helm_lint_check", CHECK_SCRIPT)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _fake(returncode: int, stdout: str = "", stderr: str = "") -> object:
    return type("FakeCompletedProcess", (), {"returncode": returncode, "stdout": stdout, "stderr": stderr})()


def _run(
    mod: types.ModuleType,
    mp: pytest.MonkeyPatch,
    root: Path,
    changed: list[str] | None = None,
    helm_cfg: dict | None = None,
) -> tuple[dict, int]:
    context: dict[str, object] = {"project_root": str(root)}
    if changed is not None:
        context["changed_files"] = changed
    if helm_cfg is not None:
        context["config"] = {"helm": helm_cfg}
    mp.setattr(sys, "stdin", io.StringIO(json.dumps(context)))
    out = io.StringIO()
    mp.setattr(sys, "stdout", out)
    with pytest.raises(SystemExit) as exc:
        mod.main()
    return json.loads(out.getvalue()), int(exc.value.code or 0)


@pytest.fixture
def chart(tmp_path: Path) -> Path:
    d = tmp_path / "charts" / "app"
    d.mkdir(parents=True)
    (d / "Chart.yaml").write_text("name: app\n")
    (d / "values.yaml").write_text("a: 1\n")
    (d / "values.schema.json").write_text("{}")
    return tmp_path


def _patch_helm(mod: types.ModuleType, mp: pytest.MonkeyPatch, handler) -> list[list[str]]:
    calls: list[list[str]] = []

    def fake_run(cmd, **kwargs):
        calls.append(cmd)
        return handler(cmd)

    mp.setattr(mod.shutil, "which", lambda name: "helm")
    mp.setattr(mod.subprocess, "run", fake_run)
    return calls


def test_skipped_when_no_chart_files_changed(chart: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    mod = _load()
    calls = _patch_helm(mod, monkeypatch, lambda cmd: _fake(0))
    result, code = _run(mod, monkeypatch, chart, changed=["src/main.py"])
    assert code == 0
    assert result["passed"] is True
    assert "skipped" in result["output"].lower()
    assert result["detail"]["status"] == "SKIPPED"
    assert result["detail"]["skip_reason"] == result["output"]
    assert calls == []


def test_skipped_when_helm_missing(chart: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    mod = _load()
    monkeypatch.setattr(mod.shutil, "which", lambda name: None)
    result, code = _run(mod, monkeypatch, chart)
    assert code == 0
    assert result["passed"] is True
    assert "helm" in result["output"]
    assert result["detail"]["status"] == "SKIPPED"


def test_skipped_when_no_charts(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    mod = _load()
    _patch_helm(mod, monkeypatch, lambda cmd: _fake(0))
    result, code = _run(mod, monkeypatch, tmp_path)
    assert code == 0
    assert "no helm chart" in result["output"].lower()
    assert result["detail"]["status"] == "SKIPPED"


def test_pass_runs_strict_lint(chart: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    mod = _load()
    calls = _patch_helm(mod, monkeypatch, lambda cmd: _fake(0, "ok"))
    result, code = _run(mod, monkeypatch, chart, changed=["charts/app/values.yaml"])
    assert code == 0
    assert result["passed"] is True
    assert calls[0][:3] == ["helm", "lint", "--strict"]


def test_lint_error_fails_with_helm_output(chart: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    mod = _load()
    _patch_helm(mod, monkeypatch, lambda cmd: _fake(1, "[ERROR] templates/: bad yaml"))
    result, code = _run(mod, monkeypatch, chart)
    assert code == 1
    assert result["passed"] is False
    assert "[ERROR] templates/: bad yaml" in result["output"]


def test_values_file_violating_schema_fails(chart: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    mod = _load()
    (chart / "charts" / "app" / "prod.yaml").write_text("bogus: 1\n")

    def handler(cmd: list[str]) -> object:
        if cmd[1] == "template":
            return _fake(1, "", "values don't meet the specifications of the schema: additional property bogus")
        return _fake(0)

    calls = _patch_helm(mod, monkeypatch, handler)
    result, code = _run(mod, monkeypatch, chart, helm_cfg={"values_files": ["prod.yaml"]})
    assert code == 1
    assert "additional property bogus" in result["output"]
    template = next(c for c in calls if c[1] == "template")
    assert "-f" in template
    assert str(chart / "charts" / "app" / "prod.yaml") in template


def test_missing_values_file_fails(chart: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    mod = _load()
    calls = _patch_helm(mod, monkeypatch, lambda cmd: _fake(0))
    result, code = _run(mod, monkeypatch, chart, helm_cfg={"values_files": ["nope.yaml"]})
    assert code == 1
    assert "nope.yaml" in result["output"]
    assert not any(c[1] == "template" for c in calls)


def test_require_schema_missing_fails(chart: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    mod = _load()
    (chart / "charts" / "app" / "values.schema.json").unlink()
    _patch_helm(mod, monkeypatch, lambda cmd: _fake(0))
    result, code = _run(mod, monkeypatch, chart, helm_cfg={"require_schema": True})
    assert code == 1
    assert "values.schema.json" in result["output"]


def test_schema_not_required_by_default(chart: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    mod = _load()
    (chart / "charts" / "app" / "values.schema.json").unlink()
    _patch_helm(mod, monkeypatch, lambda cmd: _fake(0))
    _, code = _run(mod, monkeypatch, chart)
    assert code == 0


def test_configured_charts_used(chart: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    mod = _load()
    other = chart / "other"
    other.mkdir()
    (other / "Chart.yaml").write_text("name: other\n")
    calls = _patch_helm(mod, monkeypatch, lambda cmd: _fake(0))
    _, code = _run(mod, monkeypatch, chart, helm_cfg={"charts": ["other"]})
    assert code == 0
    assert [c[-1] for c in calls if c[1] == "lint"] == [str(other)]
