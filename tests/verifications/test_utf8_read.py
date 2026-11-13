"""Verification plugins must read sources as UTF-8, not the locale encoding."""

import json
import re
import subprocess
import sys
from pathlib import Path

import pytest

VERIFICATIONS_DIR = Path(__file__).resolve().parents[2] / "src" / "ydk" / "verifications"
BARE_READ_TEXT = re.compile(r"\.read_text\(\s*\)")


@pytest.mark.parametrize("char", ["Á", "é", "中"])
def test_python_file_length_handles_non_ascii(tmp_path: Path, char: str) -> None:
    """A UTF-8 source with non-ASCII text must not crash the plugin."""
    src = tmp_path / "src"
    src.mkdir()
    (src / "mod.py").write_bytes(f"# {char}\nx = 1\n".encode())
    ctx = {"project_root": str(tmp_path), "config": {}}
    proc = subprocess.run(
        [sys.executable, str(VERIFICATIONS_DIR / "python-file-length" / "check.py")],
        input=json.dumps(ctx),
        capture_output=True,
        text=True,
        encoding="utf-8",
        env={"PYTHONUTF8": "0", "PYTHONIOENCODING": "utf-8", "PATH": ""},
        check=False,
    )
    assert proc.returncode == 0, proc.stderr
    assert json.loads(proc.stdout)["passed"] is True


def test_no_bare_read_text_in_verifications() -> None:
    """Every read_text() call under verifications passes an explicit encoding."""
    offenders = [
        f"{p.relative_to(VERIFICATIONS_DIR)}:{n}"
        for p in VERIFICATIONS_DIR.rglob("*.py")
        for n, line in enumerate(p.read_text(encoding="utf-8").splitlines(), 1)
        if BARE_READ_TEXT.search(line)
    ]
    assert offenders == []
