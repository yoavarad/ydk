"""Tests for the ydk-spec-integrity.yml CI template."""

from __future__ import annotations

from typing import TYPE_CHECKING

import yaml

from ydk.core import ci_generator
from ydk.core.ci_generator import TEMPLATES_DIR, CiContext, generate_ci, render

if TYPE_CHECKING:
    from pathlib import Path

CTX = CiContext(
    version="1.5.0",
    stack="python-cli",
    spec_location="docs/specs",
    components_path=".ydk/components",
    schemas_path=".ydk/schemas",
)


def _text(ctx: CiContext = CTX) -> str:
    return render((TEMPLATES_DIR / "ydk-spec-integrity.yml").read_text(encoding="utf-8"), ctx)


def _triggers(wf: dict) -> dict:
    return wf.get("on") or wf[True]


def test_registered() -> None:
    assert "ydk-spec-integrity.yml" in [t.output for t in ci_generator.CI_TARGETS]


def test_default_paths() -> None:
    wf = yaml.safe_load(_text())
    assert _triggers(wf)["pull_request"]["paths"] == ["docs/specs/**", ".ydk/components/**", ".ydk/schemas/**"]


def test_custom_paths_strip_trailing_slashes() -> None:
    ctx = CiContext("1.5.0", "python-cli", "specs/", "comp//", "sch/")
    wf = yaml.safe_load(_text(ctx))
    assert _triggers(wf)["pull_request"]["paths"] == ["specs/**", "comp/**", "sch/**"]


def test_structure_and_safety() -> None:
    text = _text()
    wf = yaml.safe_load(text)
    assert wf["permissions"] == {"contents": "read"}
    assert "cancel-in-progress" in wf["concurrency"]
    assert wf["env"] == {"YDK_VERSION": "1.5.0"}
    runs = [s.get("run", "") for s in wf["jobs"]["components"]["steps"]]
    assert any("ydk component validate" in r for r in runs)
    assert "spec verify" not in text
    assert "secrets." not in text


def test_generate_ci_writes_for_config_paths(tmp_path: Path) -> None:
    (tmp_path / ".ydk").mkdir()
    (tmp_path / ".ydk" / "config.yaml").write_text(
        "project:\n  name: p\n  remote: github\n  spec_location: my/specs/\n", encoding="utf-8"
    )
    generate_ci(tmp_path, force=False, version="1.5.0")
    out = tmp_path / ".github" / "workflows" / "ydk-spec-integrity.yml"
    assert _triggers(yaml.safe_load(out.read_text(encoding="utf-8")))["pull_request"]["paths"][0] == "my/specs/**"
