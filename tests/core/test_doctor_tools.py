"""Tests for stack-aware tool checks in ydk doctor."""

from __future__ import annotations

import subprocess
from typing import TYPE_CHECKING
from unittest.mock import patch

import pytest

from ydk.core.doctor import CheckSeverity, Doctor, parse_tool_version

if TYPE_CHECKING:
    from pathlib import Path

GO_VERSION_OUT = "go version go1.27.2 windows/amd64\n"
HELM_VERSION_OUT = "v4.3.0+gbec5b06\n"


def _project(tmp_path: Path, stack: str = "", extra: str = "", go_mod: str | None = None) -> Doctor:
    (tmp_path / ".ydk").mkdir()
    stack_line = f"  stack: {stack}\n" if stack else ""
    (tmp_path / ".ydk" / "config.yaml").write_text(f"project:\n  name: t\n{stack_line}{extra}")
    if go_mod is not None:
        (tmp_path / "go.mod").write_text(go_mod)
    return Doctor(project_root=tmp_path)


def _fake(present: dict[str, str]):
    """Return (which, run) fakes: tools in *present* exist and print the given version output."""

    def which(name: str) -> str | None:
        return f"/bin/{name}" if name in present else None

    def run(cmd: list[str], **_: object) -> subprocess.CompletedProcess[str]:
        out = present.get(cmd[0])
        if out is None:
            return subprocess.CompletedProcess(cmd, 1, "", "nope")
        return subprocess.CompletedProcess(cmd, 0, out, "")

    return which, run


def _results(doc: Doctor, present: dict[str, str]) -> dict[str, tuple[CheckSeverity, str]]:
    which, run = _fake(present)
    with patch("ydk.core.doctor.shutil.which", which), patch("ydk.core.doctor.subprocess.run", run):
        return {r.name: (r.severity, r.message) for r in doc._tool_checks()}


class TestParseToolVersion:
    @pytest.mark.parametrize(
        ("text", "expected"),
        [
            (GO_VERSION_OUT, "1.27.2"),
            (HELM_VERSION_OUT, "4.3.0"),
            ("Docker version 27.1.1, build 6312585", "27.1.1"),
            ("go version go1.22 linux/amd64", "1.22"),
            ("no digits", None),
        ],
    )
    def test_parse(self, text: str, expected: str | None) -> None:
        assert parse_tool_version(text) == expected


class TestGoStack:
    def test_missing_go_is_error_naming_go(self, tmp_path: Path) -> None:
        res = _results(_project(tmp_path, "go"), {})
        sev, msg = res["go"]
        assert sev == CheckSeverity.error
        assert "go" in msg

    def test_missing_gofmt_is_error(self, tmp_path: Path) -> None:
        res = _results(_project(tmp_path, "go"), {"go": GO_VERSION_OUT})
        assert res["gofmt"][0] == CheckSeverity.error

    def test_no_python_tool_checks(self, tmp_path: Path) -> None:
        res = _results(_project(tmp_path, "go"), {"go": GO_VERSION_OUT, "gofmt": ""})
        assert not {"Test runner", "Linter", "Type checker"} & set(res)

    def test_go_ok_shows_version(self, tmp_path: Path) -> None:
        res = _results(_project(tmp_path, "go"), {"go": GO_VERSION_OUT, "gofmt": ""})
        assert res["go"] == (CheckSeverity.ok, "go 1.27.2")

    def test_optional_missing_is_warning(self, tmp_path: Path) -> None:
        res = _results(_project(tmp_path, "go"), {"go": GO_VERSION_OUT, "gofmt": ""})
        for tool in ("helm", "kubectl", "kind", "docker", "trivy"):
            assert res[tool][0] == CheckSeverity.warning

    def test_optional_helm_present_ok(self, tmp_path: Path) -> None:
        res = _results(_project(tmp_path, "go"), {"go": GO_VERSION_OUT, "gofmt": "", "helm": HELM_VERSION_OUT})
        assert res["helm"] == (CheckSeverity.ok, "helm 4.3.0")

    def test_go_older_than_go_mod_toolchain_errors_with_both_versions(self, tmp_path: Path) -> None:
        doc = _project(tmp_path, "go", go_mod="module x\n\ngo 1.22\n\ntoolchain go1.28.1\n")
        sev, msg = _results(doc, {"go": GO_VERSION_OUT, "gofmt": ""})["go"]
        assert sev == CheckSeverity.error
        assert "1.27.2" in msg
        assert "1.28.1" in msg

    def test_go_mod_go_directive_used_without_toolchain(self, tmp_path: Path) -> None:
        doc = _project(tmp_path, "go", go_mod="module x\n\ngo 1.30\n")
        sev, msg = _results(doc, {"go": GO_VERSION_OUT, "gofmt": ""})["go"]
        assert sev == CheckSeverity.error
        assert "1.30" in msg

    def test_go_new_enough_for_go_mod(self, tmp_path: Path) -> None:
        doc = _project(tmp_path, "go", go_mod="module x\n\ngo 1.22.0\n")
        assert _results(doc, {"go": GO_VERSION_OUT, "gofmt": ""})["go"][0] == CheckSeverity.ok

    def test_docker_via_wsl_is_ok(self, tmp_path: Path) -> None:
        which = {"go": GO_VERSION_OUT, "gofmt": ""}

        def fake_which(name: str) -> str | None:
            return f"/bin/{name}" if name in (*which, "wsl") else None

        def fake_run(cmd: list[str], **_: object) -> subprocess.CompletedProcess[str]:
            if cmd[:2] == ["wsl", "docker"]:
                return subprocess.CompletedProcess(cmd, 0, "Docker version 27.1.1, build x", "")
            return subprocess.CompletedProcess(cmd, 0, which.get(cmd[0], ""), "")

        with patch("ydk.core.doctor.shutil.which", fake_which), patch("ydk.core.doctor.subprocess.run", fake_run):
            res = {r.name: r for r in _project(tmp_path, "go")._tool_checks()}
        assert res["docker"].severity == CheckSeverity.ok
        assert "WSL" in res["docker"].message


class TestConfigTools:
    def test_required_tool_with_min_version(self, tmp_path: Path) -> None:
        extra = "doctor:\n  required_tools:\n    - name: helm\n      min_version: '5.0'\n"
        res = _results(_project(tmp_path, "go", extra), {"go": GO_VERSION_OUT, "gofmt": "", "helm": HELM_VERSION_OUT})
        sev, msg = res["helm"]
        assert sev == CheckSeverity.error
        assert "4.3.0" in msg
        assert "5.0" in msg

    def test_bare_name_and_optional(self, tmp_path: Path) -> None:
        extra = "doctor:\n  required_tools: [jq]\n  optional_tools: [yq]\n"
        res = _results(_project(tmp_path, "go", extra), {"go": GO_VERSION_OUT, "gofmt": ""})
        assert res["jq"][0] == CheckSeverity.error
        assert res["yq"][0] == CheckSeverity.warning

    def test_config_tool_overrides_stack_default_entry(self, tmp_path: Path) -> None:
        extra = "doctor:\n  required_tools: [helm]\n"
        res = _results(_project(tmp_path, "go", extra), {"go": GO_VERSION_OUT, "gofmt": ""})
        assert res["helm"][0] == CheckSeverity.error


class TestPythonStack:
    def test_python_tool_checks_for_python_project(self, tmp_path: Path) -> None:
        doc = _project(tmp_path)
        names = [c.__name__ for c in doc._checks()]
        assert {"_check_test_runner", "_check_linter", "_check_type_checker"} <= set(names)

    def test_go_project_skips_python_tool_checks(self, tmp_path: Path) -> None:
        names = [c.__name__ for c in _project(tmp_path, "go")._checks()]
        assert not {"_check_test_runner", "_check_linter", "_check_type_checker"} & set(names)
        assert "_check_python" in names

    def test_python_project_has_no_go_checks(self, tmp_path: Path) -> None:
        assert "go" not in _results(_project(tmp_path), {})


class TestMinVersionValidation:
    def test_v_prefix_stripped(self) -> None:
        from ydk.models.config import DoctorToolSpec

        assert DoctorToolSpec(name="go", min_version="v1.20").min_version == "1.20"

    @pytest.mark.parametrize("bad", ["1.21rc1", "1.x", "latest"])
    def test_rejects_non_dotted(self, bad: str) -> None:
        from pydantic import ValidationError

        from ydk.models.config import DoctorToolSpec

        with pytest.raises(ValidationError):
            DoctorToolSpec(name="go", min_version=bad)
