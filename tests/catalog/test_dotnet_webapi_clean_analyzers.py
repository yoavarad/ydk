"""Structure tests for analyzer enforcement in the dotnet-webapi-clean pack (#519).

The generated Directory.Build.props / .editorconfig must carry the mechanically
checkable guardrails from the vendored csharp-development-best-practices skill
(§3 logging, §4 async, §5 nullability, §15 tooling), with warnings-as-errors
gated behind a single ``YdkAnalyzersAsErrors`` MSBuild property.
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest
import yaml

PACK_ROOT = Path(__file__).resolve().parents[2] / "src" / "ydk" / "catalog" / "dotnet-webapi-clean"
SCAFFOLD = PACK_ROOT / "generators" / "solution_scaffold.py"


def _scaffold_files() -> dict[str, str]:
    result = subprocess.run([sys.executable, str(SCAFFOLD)], capture_output=True, text=True, timeout=30, check=False)
    assert result.returncode == 0, result.stderr
    return {f["path"]: f["content"] for f in json.loads(result.stdout)}


@pytest.fixture(scope="module")
def props() -> ET.Element:
    return ET.fromstring(_scaffold_files()["Directory.Build.props"])


@pytest.fixture(scope="module")
def editorconfig() -> str:
    return _scaffold_files()[".editorconfig"]


def _properties(root: ET.Element, condition: str | None = None) -> dict[str, str]:
    """Merge PropertyGroup children whose group Condition equals `condition`."""
    out: dict[str, str] = {}
    for group in root.findall("PropertyGroup"):
        if group.get("Condition") == condition:
            out.update({child.tag: (child.text or "").strip() for child in group})
    return out


def _editorconfig_sections(text: str) -> dict[str, dict[str, str]]:
    sections: dict[str, dict[str, str]] = {}
    current: dict[str, str] = {}
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith(("#", ";")):
            continue
        header = re.fullmatch(r"\[(.+)\]", line)
        if header:
            current = sections.setdefault(header.group(1), {})
            continue
        key, _, value = line.partition("=")
        current[key.strip()] = value.strip()
    return sections


class TestDirectoryBuildProps:
    def test_nullable_enabled(self, props: ET.Element) -> None:
        assert _properties(props)["Nullable"] == "enable"

    def test_analysis_level_latest_recommended(self, props: ET.Element) -> None:
        assert _properties(props)["AnalysisLevel"] == "latest-recommended"

    def test_net_analyzers_and_code_style_enforced_in_build(self, props: ET.Element) -> None:
        unconditional = _properties(props)
        assert unconditional["EnableNETAnalyzers"] == "true"
        assert unconditional["EnforceCodeStyleInBuild"] == "true"

    def test_toggle_defaults_true_but_is_overridable(self, props: ET.Element) -> None:
        toggle = [el for group in props.findall("PropertyGroup") for el in group.findall("YdkAnalyzersAsErrors")]
        assert len(toggle) == 1
        assert (toggle[0].text or "").strip() == "true"
        assert toggle[0].get("Condition") == "'$(YdkAnalyzersAsErrors)' == ''"

    def test_warnings_as_errors_gated_by_toggle(self, props: ET.Element) -> None:
        assert "TreatWarningsAsErrors" not in _properties(props)
        gated = _properties(props, "'$(YdkAnalyzersAsErrors)' == 'true'")
        assert gated["TreatWarningsAsErrors"] == "true"
        assert gated["CodeAnalysisTreatWarningsAsErrors"] == "true"

    def test_threading_analyzers_package_referenced_as_private_asset(self, props: ET.Element) -> None:
        refs = [
            ref
            for group in props.findall("ItemGroup")
            for ref in group.findall("PackageReference")
            if ref.get("Include") == "Microsoft.VisualStudio.Threading.Analyzers"
        ]
        assert len(refs) == 1
        ref = refs[0]
        assert re.fullmatch(r"\d+\.\d+\.\d+", ref.get("Version") or "")
        assert (ref.findtext("PrivateAssets") or "").strip() == "all"

    def test_no_blanket_suppressions(self, props: ET.Element) -> None:
        for group in props.findall("PropertyGroup"):
            assert group.find("NoWarn") is None
            assert group.find("WarningsNotAsErrors") is None


class TestEditorconfigSeverities:
    @pytest.mark.parametrize(
        "rule",
        ["CA1849", "VSTHRD002", "CA2016", "CA1848", "CA2254"],
    )
    def test_rule_is_warning_for_all_cs(self, editorconfig: str, rule: str) -> None:
        cs = _editorconfig_sections(editorconfig)["*.cs"]
        assert cs[f"dotnet_diagnostic.{rule}.severity"] == "warning"

    def test_ca2007_off_by_default(self, editorconfig: str) -> None:
        cs = _editorconfig_sections(editorconfig)["*.cs"]
        assert cs["dotnet_diagnostic.CA2007.severity"] == "none"

    def test_ca2007_warning_for_library_projects_only(self, editorconfig: str) -> None:
        sections = _editorconfig_sections(editorconfig)
        library = [
            name for name, body in sections.items() if body.get("dotnet_diagnostic.CA2007.severity") == "warning"
        ]
        assert library == ["{Domain,Application,Infrastructure}/**.cs"]

    def test_ca2007_library_section_follows_global_cs_section(self, editorconfig: str) -> None:
        # Later editorconfig sections win, so the library override must come after [*.cs].
        assert editorconfig.index("[*.cs]") < editorconfig.index("[{Domain,Application,Infrastructure}/**.cs]")

    def test_no_rule_is_silenced(self, editorconfig: str) -> None:
        for body in _editorconfig_sections(editorconfig).values():
            for key, value in body.items():
                if key.startswith("dotnet_diagnostic.") and key != "dotnet_diagnostic.CA2007.severity":
                    assert value not in {"none", "silent"}, key


class TestPackVersion:
    def test_catalog_version_bumped(self) -> None:
        catalog = yaml.safe_load((PACK_ROOT / "catalog.yaml").read_text(encoding="utf-8"))
        assert catalog["version"] == "1.1.0"

    def test_changelog_has_entry_for_version(self) -> None:
        changelog = (PACK_ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
        assert "## 1.1.0" in changelog
        assert "YdkAnalyzersAsErrors" in changelog

    def test_readme_documents_toggle(self) -> None:
        readme = (PACK_ROOT / "README.md").read_text(encoding="utf-8")
        assert "YdkAnalyzersAsErrors" in readme
        assert "-p:YdkAnalyzersAsErrors=false" in readme
