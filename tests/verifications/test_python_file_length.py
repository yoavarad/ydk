"""Tests for the python-file-length verification plugin."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

CHECK_SCRIPT = Path(__file__).resolve().parents[2] / "src" / "ydk" / "verifications" / "python-file-length" / "check.py"


def _run(root: Path, config: dict[str, object] | None = None) -> tuple[int, dict[str, object]]:
    context: dict[str, object] = {"project_root": str(root)}
    if config is not None:
        context["config"] = config
    proc = subprocess.run(
        [sys.executable, str(CHECK_SCRIPT)],
        input=json.dumps(context),
        capture_output=True,
        text=True,
        check=False,
    )
    return proc.returncode, json.loads(proc.stdout)


def _write(path: Path, lines: int, body: str = "x = 1") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join([body] * lines) + "\n", encoding="utf-8")


def test_long_file_under_src_fails_with_default_config(tmp_path: Path) -> None:
    _write(tmp_path / "src" / "pkg" / "big.py", 301)
    code, result = _run(tmp_path)
    assert code == 1
    assert result["passed"] is False
    assert "big.py" in str(result["output"])


def test_long_file_under_app_still_fails(tmp_path: Path) -> None:
    _write(tmp_path / "app" / "big.py", 301)
    code, result = _run(tmp_path)
    assert code == 1
    assert result["passed"] is False


def test_short_files_pass(tmp_path: Path) -> None:
    _write(tmp_path / "src" / "ok.py", 300)
    code, result = _run(tmp_path)
    assert code == 0
    assert result["passed"] is True


def test_exempt_paths_skipped(tmp_path: Path) -> None:
    _write(tmp_path / "src" / "tests" / "big.py", 400)
    _write(tmp_path / "src" / "alembic" / "versions" / "big.py", 400)
    code, _ = _run(tmp_path)
    assert code == 0


def test_stub_skipped(tmp_path: Path) -> None:
    _write(tmp_path / "src" / "stub.py", 400, body="raise NotImplementedError")
    code, _ = _run(tmp_path)
    assert code == 0


def test_custom_limit(tmp_path: Path) -> None:
    _write(tmp_path / "src" / "mid.py", 50)
    code, _ = _run(tmp_path, {"file_length": {"paths": ["src"], "limit": 40}})
    assert code == 1


def test_custom_paths_replace_defaults(tmp_path: Path) -> None:
    _write(tmp_path / "src" / "big.py", 400)
    _write(tmp_path / "lib" / "big.py", 400)
    code, result = _run(tmp_path, {"file_length": {"paths": ["lib"], "limit": 300}})
    assert code == 1
    assert "lib" in str(result["output"])
    assert str(Path("src") / "big.py") not in str(result["output"])


def test_no_roots_passes_and_names_configured_roots(tmp_path: Path) -> None:
    code, result = _run(tmp_path, {"file_length": {"paths": ["lib", "pkg"], "limit": 300}})
    assert code == 0
    assert result["passed"] is True
    assert "lib" in str(result["output"])
    assert "pkg" in str(result["output"])


def test_root_under_exempt_named_dir_still_checked(tmp_path: Path) -> None:
    proj = tmp_path / ".ydk" / "tests" / "proj"
    _write(proj / "src" / "big.py", 400)
    code, _ = _run(proj)
    assert code == 1
