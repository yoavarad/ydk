"""Changelog section extraction + pyproject version helper used by release.yml."""

from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[2] / ".github" / "scripts" / "changelog_section.py"
spec = importlib.util.spec_from_file_location("changelog_section", SCRIPT)
assert spec is not None
assert spec.loader is not None
cs = importlib.util.module_from_spec(spec)
spec.loader.exec_module(cs)

CHANGELOG = """## v1.6.0 (2026-10-16)

### Feat

- **catalog**: a

### Fix

- **verify**: b

## v1.5.1 (2026-10-01)

### Fix

- old

## v1.5.0 (2026-09-01)

- older
"""


def test_extracts_top_section() -> None:
    out = cs.extract_section(CHANGELOG, "1.6.0")
    assert out.startswith("### Feat")
    assert "- **verify**: b" in out
    assert "v1.5.1" not in out
    assert "- old" not in out


def test_extracts_middle_and_last_section() -> None:
    assert cs.extract_section(CHANGELOG, "1.5.1").strip() == "### Fix\n\n- old"
    assert cs.extract_section(CHANGELOG, "v1.5.0").strip() == "- older"


def test_version_prefix_not_confused() -> None:
    with pytest.raises(LookupError):
        cs.extract_section(CHANGELOG, "1.6")


def test_missing_version_raises() -> None:
    with pytest.raises(LookupError):
        cs.extract_section(CHANGELOG, "9.9.9")


def test_project_version_reads_project_table_only() -> None:
    text = '[project]\nname = "x"\nversion = "1.2.3"\n\n[tool.commitizen]\nversion = "0.0.1"\n'
    assert cs.project_version(text) == "1.2.3"


def test_project_version_missing_raises() -> None:
    with pytest.raises(LookupError):
        cs.project_version('[project]\nname = "x"\n')


def test_cli_section(tmp_path: Path) -> None:
    f = tmp_path / "CHANGELOG.md"
    f.write_text(CHANGELOG, encoding="utf-8")
    r = subprocess.run(
        [sys.executable, str(SCRIPT), "section", "1.5.1", str(f)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert r.returncode == 0
    assert "- old" in r.stdout


def test_cli_version_and_failure(tmp_path: Path) -> None:
    p = tmp_path / "pyproject.toml"
    p.write_text('[project]\nversion = "2.0.0"\n', encoding="utf-8")
    ok = subprocess.run([sys.executable, str(SCRIPT), "version", str(p)], capture_output=True, text=True, check=False)
    assert ok.stdout.strip() == "2.0.0"
    c = tmp_path / "CHANGELOG.md"
    c.write_text(CHANGELOG, encoding="utf-8")
    bad = subprocess.run(
        [sys.executable, str(SCRIPT), "section", "9.9.9", str(c)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert bad.returncode != 0
