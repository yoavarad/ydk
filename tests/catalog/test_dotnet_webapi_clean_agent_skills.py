"""Tests for the agent-skills generator in the dotnet-webapi-clean ignition pack.

The generator vendors the csharp-development-best-practices agent skill
(SKILL.md + its reference) into the target repo's .claude/skills/ directory.
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

import yaml

PACK_ROOT = Path(__file__).resolve().parents[2] / "src" / "ydk" / "catalog" / "dotnet-webapi-clean"
SKILL_NAME = "csharp-development-best-practices"
TEMPLATE_DIR = PACK_ROOT / "templates" / "skills" / SKILL_NAME
SKILL_MD = TEMPLATE_DIR / "SKILL.md"
REFERENCE_MD = TEMPLATE_DIR / "references" / f"{SKILL_NAME}.md"
OUT_DIR = f".claude/skills/{SKILL_NAME}"


def _run_generator() -> list[dict]:
    result = subprocess.run(
        [sys.executable, str(PACK_ROOT / "generators" / "agent_skills.py")],
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=30,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert result.stderr.strip() == ""
    data = json.loads(result.stdout)
    assert isinstance(data, list)
    for item in data:
        assert set(item.keys()) == {"path", "content"}
    return data


class TestManifest:
    def test_agent_skills_generator_registered_with_no_inputs(self) -> None:
        manifest = yaml.safe_load((PACK_ROOT / "manifest.yaml").read_text())
        gens = {g["id"]: g for g in manifest["generators"]}
        assert gens["agent-skills"]["script"] == "generators/agent_skills.py"
        assert gens["agent-skills"]["inputs"] == []


class TestGeneratorOutput:
    def test_emits_skill_and_reference_paths(self) -> None:
        paths = sorted(f["path"] for f in _run_generator())
        assert paths == [f"{OUT_DIR}/SKILL.md", f"{OUT_DIR}/references/{SKILL_NAME}.md"]

    def test_content_is_vendored_template_verbatim(self) -> None:
        by_path = {f["path"]: f["content"] for f in _run_generator()}
        assert by_path[f"{OUT_DIR}/SKILL.md"] == SKILL_MD.read_text(encoding="utf-8")
        assert by_path[f"{OUT_DIR}/references/{SKILL_NAME}.md"] == REFERENCE_MD.read_text(encoding="utf-8")


def _frontmatter(text: str) -> dict:
    match = re.match(r"^---\n(.*?)\n---\n", text, re.DOTALL)
    assert match, "SKILL.md must start with YAML frontmatter"
    return yaml.safe_load(match.group(1))


def _flatten(ref_groups: list[str]) -> list[str]:
    return [n for group in ref_groups for n in re.findall(r"\d+(?:\.\d+)?", group)]


def _section_numbers(text: str) -> set[str]:
    return set(re.findall(r"^##+ (\d+(?:\.\d+)?)\.? ", text, re.MULTILINE))


class TestVendoredContent:
    def test_skill_frontmatter_name_matches_directory(self) -> None:
        meta = _frontmatter(SKILL_MD.read_text(encoding="utf-8"))
        assert meta["name"] == SKILL_NAME
        assert meta["description"]
        assert meta["license"] == "MIT"

    def test_authorship_note_present(self) -> None:
        for path in (SKILL_MD, REFERENCE_MD):
            text = path.read_text(encoding="utf-8")
            assert "MIT" in text, f"{path.name} missing MIT note"
            assert "YDK" in text, f"{path.name} missing authorship note"

    def test_section_cross_references_resolve(self) -> None:
        text = REFERENCE_MD.read_text(encoding="utf-8")
        headings = _section_numbers(text)
        refs = re.findall(r"Sections? ((?:\d+(?:\.\d+)?(?:, (?:and )?| and )?)+)", text)
        assert refs, "expected at least one Section cross-reference"
        for ref in _flatten(refs):
            assert ref in headings, f"Broken cross-reference: Section {ref}"

    def test_skill_md_section_references_resolve(self) -> None:
        headings = _section_numbers(REFERENCE_MD.read_text(encoding="utf-8"))
        refs = re.findall(r"Sections? ((?:\d+(?:\.\d+)?(?:, (?:and )?| and )?)+)", SKILL_MD.read_text(encoding="utf-8"))
        assert refs
        for ref in _flatten(refs):
            assert ref in headings, f"SKILL.md broken cross-reference: Section {ref}"

    def test_pr_checklist_is_section_16_and_referenced(self) -> None:
        text = REFERENCE_MD.read_text(encoding="utf-8")
        assert "## 16. Pull request checklist" in text
        assert "checklist in Section 16" in text
        assert "## 17. Definition of done" in text

    def test_no_draft_or_foreign_leftovers(self) -> None:
        for path in (SKILL_MD, REFERENCE_MD):
            text = path.read_text(encoding="utf-8")
            for banned in (
                "not yet the final skill definition",
                "Engineering-Handbook",
                "Playbook-Part1",
            ):
                assert banned not in text, f"{path.name} still contains {banned!r}"
            assert not re.search(r"\b(Java|Spring)\b", text), f"{path.name} has Java/Spring leftovers"

    def test_target_framework_matches_adr_0001(self) -> None:
        text = REFERENCE_MD.read_text(encoding="utf-8")
        assert "net8.0" in text
        assert "net10.0" in text
        # ADR 0001 rejects multi-targeting as the generated default.
        assert "net8.0;net10.0" not in text
        assert "TargetFrameworks" not in text
        props = (PACK_ROOT / "templates" / "solution" / "Directory.Build.props.j2").read_text(encoding="utf-8")
        assert "<TargetFramework>net8.0</TargetFramework>" in props, "pack default drifted from vendored skill"

    def test_pack_defaults_reconciled(self) -> None:
        text = REFERENCE_MD.read_text(encoding="utf-8")
        for needle in ("Minimal API", "SQLite", "ProblemDetails", "xUnit", "repository interface"):
            assert needle in text, f"reference missing pack default: {needle}"
        # Pack uses Minimal APIs (ADR 0001), not controllers.
        assert "controller" not in text.lower()

    def test_not_loaded_into_ydk_own_skills(self) -> None:
        repo_root = PACK_ROOT.parents[3]
        assert (repo_root / "skills" / "ydk" / "SKILL.md").is_file()
        assert not list((repo_root / "skills").rglob(f"*{SKILL_NAME}*"))
